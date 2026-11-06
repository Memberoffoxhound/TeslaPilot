"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
Ported to Highland (Memberoffoxhound/openpilot) from zoompilot develop
(openpilot/sunnypilot/jetlink_adapter/__init__.py) on jetlink v0.9.0's Stock
base and Hooks (API 4), matching docs/porting.md "The adapter module".
Highland changes, in short:
  - lives at openpilot/selfdrive/jetlink_adapter (no sunnypilot tree here)
  - Keys.big_model / Keys.catalog / Keys.select are Highland's model
    manager's params (openpilot/selfdrive/modelmanager)
  - in_control is jetlink's Stock rule (carState, carControl, selfdriveState):
    no MADS / carControlSP; stock modeld's warp and ModelState reset
  - get/put/remove fall back to the raw params files when the params library
    on the device predates the Jetlink keys (UnknownKeyName)
  - jetlinkd turns ADB off before the owner starts (release_adb)
  - charge_phone / link_mode helpers for Highland's Models panel

jetlink (the jetlink_repo submodule) runs the large driving model on an
attached Jetson, Mac or iPhone. Its stock adapter (jetlink.openpilot.stock)
knows stock openpilot's paths; Adapter below is that with this fork's param
names. The hooks (jetlink.openpilot.hooks) never raise and answer as if the
link were off when jetlink is not checked out, or speaks another API.

manager imports this module to build the process list, and runs it as
jetlinkd, the resident gadget owner, which stays at about 10 MB for the whole
drive. So the top level is the standard library only; everything else is
imported where it is used. tests/test_adapter.py holds the line.
"""
from __future__ import annotations

import functools
import os
import threading
from collections import namedtuple
from pathlib import Path

# the version of jetlink.openpilot's API this adapter is written to; any other
# is treated as jetlink being absent, with the reason as the offroad alert
API = 4

# the gadget owner, as manager names the process and selfdrived lists it
OWNER = 'jetlinkd'

# the Jetlink setting, stored as an index: jetlink.openpilot.MODES,
# written out so the panels build the setting without a jetlink checkout
MODES = ('off', 'usb', 'ios')

# the params jetlink reads and writes, all declared in params_keys.h. big_model
# and catalog are Highland's model manager's (openpilot/selfdrive/modelmanager),
# and select is where a pick is asked for by its ref, which jetlink writes for a
# newer pick made on the server
_Keys = namedtuple('_Keys', 'link offroad progress spec big_model catalog charge_phone select')
KEYS = _Keys(link='JetlinkLink', offroad='IsOffroad', progress='AcceleratorProgress', spec='JetlinkSpec',
             big_model='ModelManager_ActiveBundleChestnut',
             catalog='ModelManager_ModelsCache_Chestnut', charge_phone='JetlinkChargePhone',
             select='ModelManager_DownloadRef')

# every key this adapter declares in params_keys.h, and its type there
JSON_KEYS = frozenset({KEYS.progress, KEYS.spec, KEYS.big_model, KEYS.catalog})
INT_KEYS = frozenset({KEYS.link})
BOOL_KEYS = frozenset({KEYS.charge_phone})
STRING_KEYS = frozenset({KEYS.select})

# the offroad alert reason() feeds (params_keys.h, alerts_offroad.json)
OFFROAD_ALERT = 'Offroad_AcceleratorUnavailable'

# jetlink's power-off request (jetlink.comma.gadget.SHUTDOWN_REQUEST)
SHUTDOWN_REQUEST = Path('/dev/shm/jetlink-shutdown')

_AGNOS = os.path.isfile('/AGNOS')


def _params_dir() -> Path:
  """The params store's directory, by params.cc and hw.h's rule."""
  prefix = os.environ.get('OPENPILOT_PREFIX', '')
  root = os.environ.get('PARAMS_ROOT')
  if root is None:
    root = '/data/params' if _AGNOS else os.environ.get('HOME', '') + '/.comma' + prefix + '/params'
  return Path(root) / os.environ.get('OPENPILOT_PREFIX', 'd')


def link_on() -> bool:
  """Is the Jetlink setting on? As jetlink reads it, a file, so that a jetlink
  this build cannot use tells only someone who turned the link on."""
  try:
    return 0 < int((_params_dir() / KEYS.link).read_bytes()) < len(MODES)
  except (OSError, ValueError):
    return False


# kept name for Highland callers/tests that still say _link_on
_link_on = link_on


def link_mode_file() -> int:
  """The setting off the params file alone (no Params, no imports)."""
  try:
    value = int((_params_dir() / KEYS.link).read_bytes())
  except (OSError, ValueError):
    return 0
  return value if 0 <= value < len(MODES) else 0


def chestnut_cable(connected: bool | None = None) -> bool:
  """A cable on the port, for modeld's and the UI's chestnut guess: `connected`,
  or the port read now. A Jetson or an iPhone on the port is a cable too, so it
  counts only while Jetlink is off (jetlink docs/porting.md)."""
  if connected is None:
    from openpilot.common.hardware.usb import cable_connected
    connected = cable_connected()
  return connected and not link_on()


@functools.cache
def _adapter_class():
  from jetlink.openpilot.interface import Keys
  from jetlink.openpilot.stock import Stock

  class Adapter(Stock):
    """jetlink.openpilot.interface.Openpilot over Highland: stock openpilot
    but for what follows."""
    KEYS = Keys(**KEYS._asdict())

    def get(self, key: str):
      # UnknownKeyName (a params library older than the key) must not take down
      # hardwared or the UI
      try:
        return self._params().get(key)
      except Exception:
        return file_get(key)

    def put(self, key: str, value, *, block: bool = False) -> None:
      try:
        self._params().put(key, value, block=block)
      except Exception:
        file_put(key, value)

    def remove(self, key: str) -> None:
      try:
        self._params().remove(key)
      except Exception:
        file_remove(key)

    def chestnut_present(self) -> bool:
      from openpilot.selfdrive.modeld.helpers import chestnut_present
      return chestnut_present()

    @classmethod
    def main(cls) -> None:
      # AGNOS's ADB gadget holds the USB controller while AdbEnabled is set
      release_adb(link_on=True)
      super().main()

  return Adapter


def adapter():
  """The adapter, for jetlink's entry points that run as their own process."""
  return _adapter_class()()


def owner_config():
  """What jetlinkd needs: data only, so the owner imports nothing heavy."""
  return _adapter_class().owner_config()


def main() -> None:
  """jetlinkd: hold the USB gadget until manager stops this process."""
  _adapter_class().main()


def __getattr__(name: str):
  if name == 'Adapter':
    return _adapter_class()
  raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# -- params without the params library ---------------------------------------

def file_get(key: str):
  try:
    raw = (_params_dir() / key).read_bytes()
  except OSError:
    return None
  try:
    if key in JSON_KEYS:
      import json
      return json.loads(raw)
    if key in INT_KEYS:
      return int(raw)
    if key in BOOL_KEYS:
      return raw.strip() in (b'1', b'true', b'True')
    if key in STRING_KEYS:
      return raw.decode()
    return raw
  except Exception:
    return None


def file_put(key: str, value) -> None:
  if key in JSON_KEYS:
    import json
    raw = json.dumps(value).encode()
  elif key in BOOL_KEYS:
    raw = b'1' if value else b'0'
  elif key in INT_KEYS:
    raw = str(int(value)).encode()
  else:
    raw = value if isinstance(value, bytes) else str(value).encode()
  where = _params_dir()
  where.mkdir(parents=True, exist_ok=True)
  tmp = where / f'.tmp_{key}_{os.getpid()}'
  with open(tmp, 'wb') as f:
    f.write(raw)
    f.flush()
    os.fsync(f.fileno())
  os.replace(tmp, where / key)


def file_remove(key: str) -> None:
  try:
    (_params_dir() / key).unlink()
  except OSError:
    pass


def link_mode() -> int:
  """The Jetlink setting as an index into MODES; 0 when unset or unreadable."""
  try:
    from openpilot.common.params import Params
    value = Params().get(KEYS.link)
  except Exception:
    value = file_get(KEYS.link)
  try:
    value = int(value)
  except (TypeError, ValueError):
    return 0
  return value if 0 <= value < len(MODES) else 0


def set_link_mode(index: int) -> None:
  """Write the Jetlink setting; the raw file when Params rejects the key."""
  index = int(index) if 0 <= int(index) < len(MODES) else 0
  try:
    from openpilot.common.params import Params
    Params().put(KEYS.link, index, block=True)
  except Exception:
    file_put(KEYS.link, index)
  if index != 0:
    release_adb(link_on=True)


# -- ADB and the USB port -------------------------------------------------------
ADB_KEY = 'AdbEnabled'
_adb_blocked_cache: list = [-1e9, False]


def adb_blocked(max_age: float = 0.0) -> bool:
  """The link is on, so ADB must stay off. File read only; never raises."""
  try:
    import time
    now = time.monotonic()
    if max_age > 0 and now - _adb_blocked_cache[0] < max_age:
      return _adb_blocked_cache[1]
    _adb_blocked_cache[:] = [now, link_mode_file() != 0]
    return _adb_blocked_cache[1]
  except Exception:
    return False


def release_adb(link_on: bool = False) -> bool:
  """With the link on, turn ADB off if it is on. True when it changed AdbEnabled."""
  try:
    if not link_on and not adb_blocked():
      return False
    try:
      from openpilot.common.params import Params
      params = Params()
      if not params.get_bool(ADB_KEY):
        return False
      params.put_bool(ADB_KEY, False, block=True)
    except Exception:
      if (_params_dir() / ADB_KEY).read_bytes().strip() not in (b'1', b'true', b'True'):
        return False
      file_put(ADB_KEY, b'0')
    try:
      from openpilot.common.swaglog import cloudlog
      cloudlog.warning("jetlink: turned ADB off, Jetlink holds the USB port")
    except Exception:
      pass
    return True
  except Exception:
    return False


# -- the hooks ----------------------------------------------------------------

_hooks = None
_making = threading.Lock()


def hooks():
  """jetlink.openpilot.hooks.Hooks over this adapter, or the link off."""
  global _hooks
  with _making:
    if _hooks is None:
      _hooks = _guard()
    return _hooks


def _guard():
  try:
    import jetlink
    if getattr(jetlink, '__file__', None) is None:
      return _Off()
    from jetlink.openpilot.hooks import Hooks
  except ModuleNotFoundError as e:
    if e.name == 'jetlink':
      return _Off()
    if (e.name or '').startswith('jetlink.'):
      return _unusable("jetlink package too old for this build", e)
    return _unusable(f"jetlink failed to load: {e}", e)
  except Exception as e:
    return _unusable(f"jetlink failed to load: {type(e).__name__}: {e}", e)
  try:
    return Hooks(API, adapter, link_on=link_on, log=_cloudlog)
  except Exception as e:
    return _unusable(str(e), e)


def _cloudlog():
  from openpilot.common.swaglog import cloudlog
  return cloudlog


def _unusable(why: str, error: Exception) -> _Off:
  try:
    _cloudlog().error("jetlink: %s", why, exc_info=error)
  except Exception:
    pass
  return _Off(why)


class _Off:
  """Every hook with the link off; reason() says why, to someone who turned
  the link on. The fork's own: jetlink's Off cannot answer for a jetlink that
  is missing or too old to have it."""
  ANSWERS = {'should_run': False, 'status': None, 'prepare': False, 'attach': lambda model, *_: model,
             'handed_over': False, 'state': 'none', 'shutdown_step': lambda wanted, reason='': wanted,
             'model_state': None, 'lists_big_models': False, 'big_catalog': None, 'listed_ref': None,
             'swap_events': None, 'runtime': None}

  def __init__(self, why: str = ''):
    self.why = why

  def reason(self) -> str | None:
    return self.why if self.why and link_on() else None

  def __getattr__(self, name: str):
    if name not in self.ANSWERS:
      raise AttributeError(name)
    answer = self.ANSWERS[name]
    return answer if callable(answer) else lambda *args: answer


def _hook(name: str):
  def call(*args):
    return getattr(hooks(), name)(*args)
  call.__name__ = call.__qualname__ = name
  return call


# Catalog / model-list hooks bind with the link off (BINDS_WITH_LINK_OFF).
# Always-running processes (manager, modeld, hardwared, selfdrived, the UI)
# keep an early gate below so a link that is off never imports jetlink.
HOOK_NAMES = (*_Off.ANSWERS, 'reason')
(model_state, lists_big_models, big_catalog, listed_ref) = map(
  _hook, ('model_state', 'lists_big_models', 'big_catalog', 'listed_ref'))


def should_run(started: bool, params, CP) -> bool:
  return link_mode_file() != 0 and hooks().should_run(started, params, CP)


def status():
  """One snapshot for the UI, or None with the link off (no jetlink import)."""
  return hooks().status() if link_mode_file() != 0 else None


def reason() -> str | None:
  return hooks().reason() if link_mode_file() != 0 else None


def runtime():
  return hooks().runtime() if link_mode_file() != 0 else None


def prepare(chestnut: bool) -> bool:
  return not chestnut and link_mode_file() != 0 and hooks().prepare(chestnut)


def attach(model, small, cam_w: int, cam_h: int):
  if _hooks is None or small is None:
    return model
  return hooks().attach(model, small, cam_w, cam_h)


def handed_over(model) -> bool:
  """Did the joining model change which model drives? Reads the model alone."""
  return bool(hooks().handed_over(model)) if _hooks is not None else False


def state(model) -> str:
  try:
    return str(getattr(model, 'big_model_state', 'none'))
  except Exception:
    return 'none'


def shutdown_step(wanted: bool, reason: str = '') -> bool:
  if link_mode_file() == 0 and _hooks is None and not SHUTDOWN_REQUEST.exists():
    return wanted
  return hooks().shutdown_step(wanted, reason)


def swap_events(tick_s: float):
  return hooks().swap_events(tick_s) if link_mode_file() != 0 else None


def jetlink_available() -> bool:
  """Is a jetlink this build can use checked out here?"""
  return not isinstance(hooks(), _Off)


def default_big_model(chestnut: bool, jetlink) -> str:
  """What an empty big-model slot runs, by name: jetlink's default with no
  chestnut fitted. `jetlink` is a status() snapshot or None."""
  try:
    from jetlink.registry.catalog import DEFAULT_BIG_MODEL_NAME
    default = str(DEFAULT_BIG_MODEL_NAME)
  except Exception:
    default = "default"
  if not chestnut and jetlink is not None and getattr(jetlink, 'default_model', None):
    return jetlink.default_model
  return default


def charge_phone() -> bool:
  try:
    from openpilot.common.params import Params
    return bool(Params().get_bool(KEYS.charge_phone))
  except Exception:
    return file_get(KEYS.charge_phone) is True


def set_charge_phone(on: bool) -> None:
  try:
    from openpilot.common.params import Params
    Params().put_bool(KEYS.charge_phone, bool(on), block=True)
  except Exception:
    file_put(KEYS.charge_phone, bool(on))
