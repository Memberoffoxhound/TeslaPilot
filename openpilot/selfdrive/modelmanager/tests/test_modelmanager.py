"""Highland's model manager and its Jetlink wiring.

Ported from zoompilot's sunnypilot/models/tests/test_manager_download.py and
test_default_bootstrap.py (the big-model slot, the catalog cache, fetcher_zp's
refetch on a hardware change, an empty catalog never resetting the pick, a
dropped model falling back to the default), on Highland's dict bundles. New
here: the raw-file fallbacks for a params library older than the keys, the
default catalog before the first fetch, and a pick resolving through jetlink
itself (Models.selected_model and link.identity).

Every test runs on the raw param files (no params library on the box, which is
the stale-library case on a device), under a PARAMS_ROOT of its own.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive import modelmanager as mm
from openpilot.selfdrive.modelmanager import store
from openpilot.selfdrive.modelmanager.manager import ModelManager
from openpilot.selfdrive.ui import model_picker as mp

ROOT = Path(__file__).resolve().parents[4]
REF_A = 'a' * 40
REF_B = 'b' * 40
REF_OLD = 'c' * 40


def bundle(ref, name, index, folder='Big Models', selector='20'):
  return {'short_name': name[:4].upper(), 'display_name': f'{name} (October 01, 2026)', 'ref': ref, 'index': index,
          'minimum_selector_version': selector, 'generation': '12', 'environment': 'release', 'runner': 'tinygrad',
          'is_20hz': True, 'is_big': True, 'overrides': {'folder': folder}, 'models': []}


CATALOG = {'tinygrad_ref': 'x', 'bundles': [bundle(REF_A, 'Alpha', 1), bundle(REF_B, 'Bravo', 2, folder='New'),
                                            bundle(REF_OLD, 'Old', 3, selector='19')]}


@pytest.fixture(autouse=True)
def params_root(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  store._store.clear()
  # no params library here: Params() fails and every read is the file
  monkeypatch.setattr(store, '_params', mock.Mock(side_effect=ImportError('no params_pyx')))
  monkeypatch.setattr(ja, 'accel_mode', lambda chestnut=None: 'none')
  monkeypatch.setattr(ja, 'big_catalog', lambda selector: (_ for _ in ()).throw(AssertionError('big_catalog')))
  monkeypatch.setattr(ja, 'listed_ref', lambda ref: None)
  return tmp_path / 'd'


class Clock:
  def __init__(self, t=1000.0):
    self.t = t

  def __call__(self):
    return self.t


def manager(fetch=None, clock=None, mode=None):
  return ModelManager(fetch=fetch or mock.Mock(return_value=json.loads(json.dumps(CATALOG))), clock=clock or Clock(),
                      wall=lambda: 1_790_000_000, log=mock.Mock(), mode=mode)


# -- keys and params ----------------------------------------------------------------

def test_keys_declared_without_backup():
  header = (ROOT / 'openpilot/common/params_keys.h').read_text()
  for key in mm.KEY_TYPES:
    line = next((ln for ln in header.splitlines() if f'{{"{key}",' in ln), None)
    assert line is not None, key
    assert 'BACKUP' not in line
  assert 'BACKUP' not in header


def test_jetlink_keys_are_the_model_managers():
  assert ja.KEYS.big_model == 'ModelManager_ActiveBundleChestnut' == mm.ACTIVE_BIG
  assert ja.KEYS.catalog == 'ModelManager_ModelsCache_Chestnut' == mm.CACHE_BIG
  assert ja.KEYS.select == mm.DOWNLOAD_REF
  assert mm.REQUIRED_JSON_VERSION == 20


@pytest.mark.parametrize('key,value', [(mm.ACTIVE_BIG, {'ref': REF_A, 'displayName': 'Alpha'}), (mm.SYNC_BIG, 12345),
                                       (mm.DOWNLOAD_REF, REF_B), (mm.STATUS, {'state': 'idle'})])
def test_store_falls_back_to_the_raw_file(params_root, key, value):
  store.put(key, value)
  raw = (params_root / key).read_bytes()
  assert raw == (json.dumps(value).encode() if isinstance(value, dict) else str(value).encode())
  assert store.get(key) == value
  store.remove(key)
  assert store.get(key) is None and not (params_root / key).exists()


def test_store_reads_a_garbled_file_as_unset(params_root):
  params_root.mkdir(parents=True)
  (params_root / mm.CACHE_BIG).write_bytes(b'{not json')
  assert store.get(mm.CACHE_BIG) is None
  assert mp.bundles() == []


def test_store_uses_params_when_it_knows_the_key(monkeypatch):
  fake = mock.Mock()
  fake.get.return_value = {'ref': REF_A}
  monkeypatch.setattr(store, '_params', lambda: fake)
  assert store.get(mm.ACTIVE_BIG) == {'ref': REF_A}
  store.put(mm.ACTIVE_BIG, {'ref': REF_B})
  fake.put.assert_called_once_with(mm.ACTIVE_BIG, {'ref': REF_B}, block=True)


def test_default_big_model_uses_the_index():
  from jetlink.registry.index import DEFAULT_BIG_MODEL_NAME
  assert ja.default_big_model(False, None) == DEFAULT_BIG_MODEL_NAME
  status = mock.Mock(default_model='From Status')
  assert ja.default_big_model(False, status) == 'From Status'
  assert ja.default_big_model(True, status) == 'comma big model'


# -- the catalog -------------------------------------------------------------------

def test_catalog_lists_selector_20_newest_first():
  assert [b['ref'] for b in mm.catalog_bundles(CATALOG)] == [REF_B, REF_A]
  assert mm.catalog_bundles(None) == [] and mm.catalog_bundles({'bundles': 'x'}) == []


def test_first_step_fetches_and_caches():
  m = manager()
  m.step()
  m.fetch.assert_called_once()
  assert store.get(mm.CACHE_BIG)['bundles'][0]['ref'] == REF_A
  assert store.get(mm.SYNC_BIG) == int(1000.0 * 1e9)
  assert store.get(mm.STATUS)['state'] == 'idle' and store.get(mm.STATUS)['models'] == 2


def test_matching_cache_is_used_without_fetch():
  clock = Clock()
  m = manager(clock=clock)
  m.step()
  clock.t += 600
  m.step()
  assert m.fetch.call_count == 1


def test_cache_expires_after_an_hour_and_on_refresh():
  clock = Clock()
  m = manager(clock=clock)
  m.step()
  clock.t += mm.CACHE_TIMEOUT
  m.step()
  assert m.fetch.call_count == 2
  mp.refresh()
  m.step()
  assert m.fetch.call_count == 3


def test_corrupt_cache_is_refetched(params_root):
  m = manager()
  m.step()
  (params_root / mm.CACHE_BIG).write_bytes(b'garbage')
  store.put(mm.SYNC_BIG, 0)
  m.step()
  assert m.fetch.call_count == 2 and mm.catalog_bundles(store.get(mm.CACHE_BIG))


def test_failed_fetch_keeps_the_cache_and_backs_off():
  clock = Clock()
  m = manager(clock=clock)
  m.step()
  m.fetch.side_effect = OSError('offline')
  store.put(mm.SYNC_BIG, 0)
  m.step()
  assert store.get(mm.STATUS)['state'] == 'failed'
  assert mm.catalog_bundles(store.get(mm.CACHE_BIG))
  for _ in range(5):
    clock.t += 1
    m.step()
  assert m.fetch.call_count == 2  # backing off, not a request a second
  clock.t += 30
  m.step()
  assert m.fetch.call_count == 3
  mp.refresh()  # the UI's refresh skips the back-off
  m.step()
  assert m.fetch.call_count == 4


def test_offline_first_boot_does_not_spin():
  clock = Clock()
  m = manager(fetch=mock.Mock(side_effect=OSError('offline')), clock=clock)
  for _ in range(10):
    clock.t += 1
    m.step()
  assert m.fetch.call_count == 1


def test_empty_catalog_is_not_cached():
  m = manager(fetch=mock.Mock(return_value={'bundles': []}))
  m.step()
  assert store.get(mm.CACHE_BIG) is None and store.get(mm.STATUS)['state'] == 'failed'


def test_catalog_is_jetlinks_index(monkeypatch):
  extra = bundle('d' * 40, 'Delta', 9)
  monkeypatch.setattr(ja, 'big_catalog', lambda selector: {'bundles': [extra, *CATALOG['bundles']]})
  ModelManager(clock=Clock(), log=mock.Mock()).step()
  assert mm.catalog_bundles(store.get(mm.CACHE_BIG))[0]['ref'] == 'd' * 40


def test_chestnut_keeps_its_own_pick(monkeypatch):
  mode = ['none']
  monkeypatch.setattr(ja, 'accel_mode', lambda chestnut=None: mode[0])
  m = manager(mode=lambda: mode[0])
  mp.select(REF_A)
  m.step()
  mode[0] = 'chestnut'
  assert mp.picked() is None and mp.bundles() == []
  m.step()
  assert store.get(mm.CHESTNUT_CACHE) and mp.picked() is None
  mp.select(REF_B)
  m.step()
  assert store.get(mm.CHESTNUT_PICK)['ref'] == REF_B
  mode[0] = 'jetlink'
  assert mp.picked()['ref'] == REF_A


def test_pick_is_stored_without_files():
  m = manager()
  m.step()
  mp.select(REF_B)
  m.step()
  slot = store.get(mm.ACTIVE_BIG)
  assert slot['ref'] == REF_B and slot['displayName'] == 'Bravo (October 01, 2026)' and slot['models'] == []
  assert slot['minimumSelectorVersion'] == 20 and {'key': 'folder', 'value': 'New'} in slot['overrides']
  assert store.get(mm.DOWNLOAD_REF) is None
  assert mp.big_model_label() == 'bravo'


def test_pick_waits_for_a_catalog():
  m = manager(fetch=mock.Mock(side_effect=OSError('offline')))
  mp.select(REF_B)
  m.step()
  assert store.get(mm.DOWNLOAD_REF) == REF_B and store.get(mm.ACTIVE_BIG) is None


def test_unlisted_pick_is_refused():
  m = manager()
  m.step()
  mp.select(REF_OLD)  # selector 19: not for this build
  m.step()
  assert store.get(mm.ACTIVE_BIG) is None and store.get(mm.DOWNLOAD_REF) is None
  assert store.get(mm.STATUS)['state'] == 'failed'


def test_a_model_the_new_catalog_lacks_falls_back_to_the_default(monkeypatch):
  m = manager()
  store.put(mm.ACTIVE_BIG, {'ref': 'e' * 40, 'displayName': 'Withdrawn'})
  m.step()
  assert store.get(mm.ACTIVE_BIG) is None


def test_listed_ref_carries_a_recompile_over(monkeypatch):
  """A pick whose ONNX is listed under a newer ref is queued, not dropped."""
  new_ref = 'f' * 40
  monkeypatch.setattr(ja, 'listed_ref', lambda ref: new_ref if ref == 'e' * 40 else None)
  catalog = {'bundles': [bundle(new_ref, 'Rebuilt', 5), *CATALOG['bundles']]}
  store.put(mm.ACTIVE_BIG, {'ref': 'e' * 40, 'displayName': 'Train Track'})
  manager().validate_pick(catalog)
  assert store.get(mm.DOWNLOAD_REF) == new_ref
  assert store.get(mm.ACTIVE_BIG)['ref'] == 'e' * 40  # still the old until the queue applies


def test_offline_keeps_the_pick():
  store.put(mm.ACTIVE_BIG, {'ref': 'e' * 40, 'displayName': 'Kept'})
  m = manager(fetch=mock.Mock(side_effect=OSError('offline')))
  m.step()
  assert store.get(mm.ACTIVE_BIG)['ref'] == 'e' * 40


def test_empty_catalog_does_not_reset_the_pick():
  store.put(mm.ACTIVE_BIG, {'ref': REF_A, 'displayName': 'Alpha'})
  manager(fetch=mock.Mock(return_value={'bundles': []})).step()
  assert store.get(mm.ACTIVE_BIG)['ref'] == REF_A


def test_reset_to_default():
  store.put(mm.ACTIVE_BIG, {'ref': REF_A})
  store.put(mm.DOWNLOAD_REF, REF_B)
  mp.reset_to_default()
  assert store.get(mm.ACTIVE_BIG) is None and store.get(mm.DOWNLOAD_REF) is None
  assert mp.big_model_label().endswith('(default)')


def test_a_failing_step_never_kills_the_loop(monkeypatch):
  m = manager()
  monkeypatch.setattr(m, 'process_request', mock.Mock(side_effect=RuntimeError('boom')))
  m.step()
  m.log.exception.assert_called()


# -- the picker's lists ------------------------------------------------------------

def test_folders_newest_first():
  store.put(mm.CACHE_BIG, CATALOG)
  assert [(f, [b['ref'] for b in bs]) for f, bs in mp.folders()] == [('New', [REF_B]), ('Big Models', [REF_A])]
  assert mp.list_label().startswith('2 models')


# -- through jetlink ---------------------------------------------------------------

def _jetlink_op():
  pytest.importorskip('jetlink.openpilot.models')
  a = ja.Adapter()
  # Stock's cached properties, without swaglog / basedir imports
  a.__dict__.update(log=mock.Mock(), basedir=ROOT)
  return a


def test_jetlink_runs_the_pick(params_root):
  op = _jetlink_op()
  from jetlink.openpilot.models import Models
  m = manager()
  m.step()
  # v0.9.0: catalog() became the index; selected_slot / selected_model still drive
  mp.select(REF_A)
  m.step()
  models = Models(op)
  slot = models.selected_slot()
  assert slot is not None and slot.get('ref') == REF_A
  assert models.selected_model()['ref'] == REF_A


def test_jetlink_default_with_no_pick():
  op = _jetlink_op()
  from jetlink.openpilot.models import Models
  with mock.patch.object(ja.Adapter, '_params', side_effect=ImportError):
    selected = Models(op).selected_model()
    assert selected and selected.get('ref')
    default_ref = selected['ref']
    store.put(mm.CACHE_BIG, {'bundles': [*CATALOG['bundles'], bundle(default_ref, 'Default Big', 0)]})
    assert Models(op).selected_model()['ref'] == default_ref


def test_big_catalog_selector_is_required_json_version(monkeypatch):
  """modelmanagerd passes REQUIRED_JSON_VERSION into big_catalog (zoompilot)."""
  seen = []
  monkeypatch.setattr(ja, 'big_catalog', lambda selector: seen.append(selector) or {'bundles': CATALOG['bundles']})
  ModelManager(clock=Clock(), log=mock.Mock()).step()
  assert seen == [mm.REQUIRED_JSON_VERSION]


# -- manager and selfdrived --------------------------------------------------------

def test_manager_registers_modelmanagerd():
  src = (ROOT / 'openpilot/system/manager/process_config.py').read_text()
  assert ('RestartingPythonProcess("modelmanagerd", "openpilot.selfdrive.modelmanager.manager", only_offroad, enabled=not PC)'
          in src)


def test_selfdrived_never_waits_for_modelmanagerd():
  src = (ROOT / 'openpilot/selfdrive/selfdrived/selfdrived.py').read_text()
  assert "p.name not in {'modelmanagerd', *JetlinkEvents.OPTIONAL_PROCESSES}" in src


def test_modelmanager_imports_light():
  """manager, the UI and process_config import these: nothing heavy at import."""
  for path in (ROOT / 'openpilot/selfdrive/modelmanager').glob('*.py'):
    tree = ast.parse(path.read_text())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {(n.module or '') if isinstance(n, ast.ImportFrom) else n.names[0].name for n in top}
    assert not names & {'numpy', 'tinygrad', 'cereal', 'requests', 'openpilot.common.params'}, (path.name, names)


# -- the mici page, over stand-in widgets (no raylib on the test box) ---------------

class _Widget:
  def __init__(self, text='', value='', *a, **k):
    self.text, self.value, self.cb, self.enabled = text, value, None, True

  def set_click_callback(self, cb):
    self.cb = cb

  def set_enabled(self, enabled):
    self.enabled = enabled

  def get_value(self):
    return self.value

  def set_value(self, value):
    self.value = value

  def set_visible(self, visible):
    self.visible = visible

  def set_text(self, text):
    self.text = text

  def set_long_press_callback(self, cb):
    self.long_press = cb


class _Scroller:
  def __init__(self):
    self.widgets = []

  def add_widgets(self, widgets):
    self.widgets += widgets


class _NavScroller:
  def __init__(self, **k):
    self._scroller = _Scroller()

  def show_event(self):
    pass

  def _update_state(self):
    pass


@pytest.fixture
def page(monkeypatch):
  import importlib
  import sys
  import types
  gui = SimpleNamespace(stack=[], push_widget=None, pop_widgets_to=None)
  gui.push_widget = gui.stack.append
  gui.pop_widgets_to = lambda w: gui.stack.clear()
  class _Info:
    def __init__(self, *info):
      self.info = info

    def set_info(self, *info):
      self.info = info

  class _Link(_Widget):
    def refresh(self):
      pass

    def set_visible(self, visible):
      self.visible = visible

  class _Toggle(_Widget):
    def __init__(self, text='', *a, initial_state=False, toggle_callback=None, **k):
      super().__init__(text)
      self.checked, self.toggle_callback = initial_state, toggle_callback

    def set_checked(self, checked):
      self.checked = checked

    def set_visible(self, visible):
      self.visible = visible

  jetlink = SimpleNamespace(active_model=None, standin=None, progress={'stage': 'download', 'frac': 0.5, 'msg': 'train track'})
  fakes = {
    'openpilot.selfdrive.ui.mici.widgets.button': {'BigButton': _Widget, 'GreyBigButton': _Widget, 'BigToggle': _Toggle},
    'openpilot.selfdrive.ui.mici.layouts.settings.model_widgets': {'CurrentModelInfo': _Info, 'JetlinkIosToggle': _Link},
    'openpilot.selfdrive.ui.ui_state': {'ui_state': SimpleNamespace(started=False, jetlink=jetlink, chestnut_present=False,
                                                                    chestnut_state=SimpleNamespace(value='loading'))},
    'openpilot.selfdrive.ui.mici.widgets.dialog': {'SettingDescriptionDialog': _Widget},
    'openpilot.system.ui.lib.application': {'gui_app': gui},
    'openpilot.system.ui.widgets.scroller': {'NavScroller': _NavScroller},
  }
  for name, attrs in fakes.items():
    monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**attrs))
  monkeypatch.delitem(sys.modules, 'openpilot.selfdrive.ui.mici.layouts.settings.models', raising=False)
  mod = importlib.import_module('openpilot.selfdrive.ui.mici.layouts.settings.models')
  return mod, gui


def test_models_page_picks_and_resets(page):
  mod, gui = page
  store.put(mm.CACHE_BIG, CATALOG)
  p = mod.ModelsLayoutMici()
  p._update_state()
  assert p._big.value.endswith('(default)') and p._info.info[1:] == ('big model', 'train track 50%')
  assert p._info.info[0] == mp.SMALL_MODEL.lower()
  assert p._refresh.value.startswith('2 models')
  p._big.cb()                      # the folders
  folders = gui.stack[-1]._scroller.widgets
  assert [w.text for w in folders] == [f'{mp.default_name()} ({mp.DEFAULT_LABEL})'.lower(), 'new', 'big models']
  folders[1].cb()                  # the models in "new"
  models = gui.stack[-1]._scroller.widgets
  assert [w.text for w in models] == ['bravo']
  models[0].cb()
  assert store.get(mm.DOWNLOAD_REF) == REF_B and gui.stack == []
  manager().process_request()
  p._tick = 0
  p._update_state()
  assert p._big.value == 'bravo'
  p._reset.cb()
  assert store.get(mm.ACTIVE_BIG) is None
  p._refresh.cb()
  assert store.get(mm.SYNC_BIG) == 0


def test_models_page_locked_onroad(page):
  mod, _ = page
  p = mod.ModelsLayoutMici()
  mod.ui_state.started = True
  assert not p._big.enabled() and not p._refresh.enabled() and not p._reset.enabled()
  assert not p._link.enabled()


def test_models_page_per_mode(page, monkeypatch, tmp_path):
  from openpilot.selfdrive.modeld import helpers
  mod, gui = page
  mode = ['none']
  monkeypatch.setattr(ja, 'accel_mode', lambda chestnut=None: mode[0])
  monkeypatch.setattr(helpers, 'CHESTNUT_DIR', tmp_path / 'models')
  p = mod.ModelsLayoutMici()
  p.show_event()
  assert not p._big.visible and not p._refresh.visible and p._link.visible
  mode[0] = 'chestnut'
  store.put(mm.CHESTNUT_CACHE, CATALOG)
  p.show_event()
  assert p._big.visible and not p._link.visible and p._big.text == 'chestnut big model'
  p._update_state()
  assert p._big.value == 'comma big model (default)'
  assert mp.model_note(REF_A) == 'compiles on device'
  store.put(mm.CHESTNUT_PICK, {'ref': REF_A, 'displayName': 'Alpha'})
  store.put(mm.CHESTNUT_PROGRESS, {'ref': REF_A, 'stage': 'compiling', 'frac': 0.0, 'msg': 'compiling on chestnut'})
  assert mp.model_note(REF_A) == 'compiling...'
  p._tick = 0
  p._update_state()
  assert p._info.info[1:] == ('big model', 'compiling on chestnut')
  store.put(mm.CHESTNUT_FAILED, REF_A)
  store.remove(mm.CHESTNUT_PROGRESS)
  assert mp.model_note(REF_A) == 'failed'
  mp.select(REF_A)
  assert store.get(mm.CHESTNUT_FAILED) is None and store.get(mm.CHESTNUT_REF) == REF_A
  mode[0] = 'jetlink'
  p.show_event()
  assert p._big.text == 'jetlink big model' and p._link.visible and mp.picked() is None


def test_compile_progress_renders_like_jetlink_and_stays_out_of_jetlink(page, monkeypatch, tmp_path):
  from openpilot.selfdrive.modeld import helpers
  from openpilot.selfdrive.ui import accelerator_link as al
  mod, gui = page
  mode = ['chestnut']
  monkeypatch.setattr(ja, 'accel_mode', lambda chestnut=None: mode[0])
  monkeypatch.setattr(helpers, 'CHESTNUT_DIR', tmp_path / 'models')
  store.put(mm.CHESTNUT_CACHE, CATALOG)
  store.put(mm.CHESTNUT_PICK, {'ref': REF_A, 'displayName': 'Alpha'})
  store.put(mm.CHESTNUT_PROGRESS, {'ref': REF_A, 'stage': 'compiling', 'frac': 0.42, 'msg': 'compiling'})
  p = mod.ModelsLayoutMici()
  p.show_event()
  p._tick = 0
  p._update_state()
  assert p._info.info[1:] == ('big model', 'compiling 42%') and mp.model_note(REF_A) == 'compiling 42%'
  # a Jetlink build at the same point reads the same
  jl = SimpleNamespace(progress={'stage': 'compile', 'frac': 0.42, 'msg': 'compiling'}, active_model=None, mode='usb')
  assert al.model_info(jl, 'loading', False, progress=jl.progress)[1:] == ('big model', 'compiling 42%')
  # Jetlink with the same ref picked never sees a stale chestnut compile
  store.put(mm.CHESTNUT_PROGRESS, {'ref': REF_A, 'stage': 'failed', 'frac': 0.0, 'msg': 'failed: boom'})
  store.put(mm.ACTIVE_BIG, {'ref': REF_A, 'displayName': 'Alpha'})
  mode[0] = 'jetlink'
  assert mp.compile_progress() is None and mp.compile_progress('jetlink') is None
  assert mp.compile_progress('chestnut') is not None
