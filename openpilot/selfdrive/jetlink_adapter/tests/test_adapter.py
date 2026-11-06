"""Highland's Jetlink adapter: matches zoompilot develop's thin Stock/Hooks
module (API 4). Off means off, conformance, and the interface jetlink holds
the adapter to.
"""
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from openpilot.selfdrive import jetlink_adapter as ja

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def params_root(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  ja._hooks = None
  return tmp_path / 'd'


def _write_link(params_root, index: int):
  params_root.mkdir(parents=True, exist_ok=True)
  (params_root / 'JetlinkLink').write_bytes(str(index).encode())


def test_top_level_is_stdlib_only():
  heavy = "('numpy', 'zmq', 'capnp', 'jetlink', 'openpilot.common.params')"
  code = f"import sys; import openpilot.selfdrive.jetlink_adapter; print([m for m in {heavy} if m in sys.modules])"
  out = subprocess.check_output([sys.executable, '-c', code], cwd=ROOT, text=True).strip()
  assert out == '[]'


def test_link_on_reads_the_file(params_root):
  assert not ja.link_on()
  _write_link(params_root, 1)
  assert ja.link_on()
  _write_link(params_root, 0)
  assert not ja.link_on()


def test_off_answers_as_the_link_off(params_root):
  assert not ja.link_on()
  assert ja.should_run(False, None, None) is False
  assert ja.should_run(True, None, None) is False
  assert ja.prepare(False) is False
  small = object()
  assert ja.attach(small, small, 1344, 760) is small
  # zoompilot: status() may return a Status with enabled=False when Hooks bind
  status = ja.status()
  assert status is None or getattr(status, 'enabled', None) is False
  assert ja.reason() is None
  # Hooks.swap_events builds a tracker even with the link off (BINDS); Off answers None
  swaps = ja.swap_events(0.01)
  assert swaps is None or type(swaps).__name__ == 'SwapTracker'
  assert ja.shutdown_step(False) is False and ja.shutdown_step(True, 'test') is True
  assert ja.handed_over(small) is False and ja.state(small) == 'none'
  # lists_big_models binds with the link off (no chestnut => True)
  assert isinstance(ja.lists_big_models(), bool)


def test_chestnut_wins(params_root):
  _write_link(params_root, 2)
  assert ja.prepare(True) is False


def test_api_and_modes_match_jetlink():
  jl = pytest.importorskip('jetlink.openpilot')
  from jetlink.openpilot import interface
  assert jl.API == ja.API == 4
  assert interface.MODES == ja.MODES


def test_conformance():
  pytest.importorskip('jetlink.openpilot.stock')
  from jetlink.openpilot.interface import Openpilot, conformance
  from jetlink.openpilot.stock import Stock
  a = ja.adapter()
  a.__dict__.update(log=None, basedir=ROOT)
  assert isinstance(a, Stock)
  assert conformance(a, Openpilot) == []
  assert a.keys.progress == 'AcceleratorProgress' and a.keys.big_model == 'ModelManager_ActiveBundleChestnut'
  assert a.keys.charge_phone == 'JetlinkChargePhone'  # KEYS match zoompilot; no UI toggle
  assert a.keys.select == 'ModelManager_DownloadRef'
  assert a.IN_CONTROL_SERVICES == ('carState', 'carControl', 'selfdriveState')
  assert a.warp_path(1344, 760, 512, 256) == ROOT / 'openpilot/selfdrive/modeld/models/driving_warp_1344x760_tinygrad.pkl'


def test_jetlinks_adapter_check():
  testing = pytest.importorskip('jetlink.openpilot.testing')
  assert testing.check_adapter(ja, heavy=('openpilot.common.params', 'openpilot.common.swaglog', 'openpilot.cereal')) == []


def test_the_fallback_answers_as_the_link_off(params_root):
  testing = pytest.importorskip('jetlink.openpilot.testing')
  assert testing.check_fallback(ja._Off("jetlink package API 9, this build expects 4"), ja.HOOK_NAMES, link_on=ja.link_on) == []
  _write_link(params_root, 1)
  assert ja._Off("why").reason() == "why"
  _write_link(params_root, 0)
  assert ja._Off("why").reason() is None


def test_hooks_without_a_checkout_are_the_link_off(monkeypatch):
  monkeypatch.setitem(sys.modules, 'jetlink', None)
  ja._hooks = None
  assert isinstance(ja._guard(), ja._Off)


def test_hooks_are_jetlinks_with_a_checkout():
  pytest.importorskip('jetlink.openpilot.hooks')
  from jetlink.openpilot.hooks import Hooks
  ja._hooks = None
  assert isinstance(ja._guard(), Hooks)


def test_keys_declared():
  header = (ROOT / 'openpilot/common/params_keys.h').read_text()
  declared = set(re.findall(r'\{"(\w+)",', header))
  wanted = {k for k in ja.KEYS if k}
  assert wanted <= declared, wanted - declared
  assert 'JetlinkModelPointers' not in declared  # dropped with API 4 / zoompilot


def test_manager_registers_jetlinkd():
  src = (ROOT / 'openpilot/system/manager/process_config.py').read_text()
  assert 'RestartingPythonProcess(jetlink_adapter.OWNER, "openpilot.selfdrive.jetlink_adapter", jetlink_adapter.should_run' in src
  assert importlib.util.find_spec('openpilot.selfdrive.jetlink_adapter') is not None


def test_submodule_pin():
  gm = (ROOT / '.gitmodules').read_text()
  assert 'path = jetlink_repo' in gm and 'zoompilot/jetlink' in gm


def test_launch_draws_nothing_from_the_port_from_boot():
  src = (ROOT / 'launch_chffrplus.sh').read_text()
  line = 'sudo -n bash jetlink/comma/jetlink-root.sh boot /data/params/d/JetlinkLink &'
  assert line in src
  assert src.index('ln -sfn jetlink_repo/jetlink jetlink') < src.index(line) < src.index('agnos_init\n  fi')


@pytest.mark.parametrize('cable,link,counted', [(False, False, False), (True, False, True), (True, True, False)])
def test_the_cable_counts_only_with_the_link_off(monkeypatch, cable, link, counted):
  from openpilot.common.hardware import usb
  monkeypatch.setattr(usb, 'cable_connected', lambda: cable)
  monkeypatch.setattr(ja, 'link_on', lambda: link)
  assert ja.chestnut_cable() is counted


def test_modeld_asks_the_adapter_about_the_cable():
  from openpilot.common.basedir import BASEDIR
  source = (Path(BASEDIR) / 'openpilot/selfdrive/modeld/modeld.py').read_text()
  assert 'jetlink_adapter.chestnut_cable()' in source
  assert 'cable_connected' not in source
  # zoompilot style: module-level prepare/attach hooks
  assert 'jetlink_adapter.prepare(' in source
  assert 'jetlink_adapter.attach(' in source


def test_select_is_the_model_managers_queue():
  from openpilot.selfdrive import modelmanager as mm
  assert ja.KEYS.select == mm.DOWNLOAD_REF
