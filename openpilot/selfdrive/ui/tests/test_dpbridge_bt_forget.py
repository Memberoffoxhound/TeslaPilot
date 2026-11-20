"""Settings > bluetooth forget: the row clears once the device is gone or unpaired, or after FORGET_S."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROBE = textwrap.dedent('''
  import json, os, sys, types
  PHONE = "AA:BB:CC:DD:EE:02"

  class FakeParams:
    store: dict = {}
    def __init__(self, *a, **kw):
      pass
    def get(self, k, *a, **kw):
      return self.store.get(k)
    def get_bool(self, k, *a, **kw):
      return bool(self.store.get(k))
    def put(self, k, v, *a, **kw):
      self.store[k] = v
    put_bool = put
    def remove(self, k):
      self.store.pop(k, None)

  sys.modules["openpilot.common.params"] = types.SimpleNamespace(Params=FakeParams)
  import raylib_nb as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.selfdrive.ui.mici.layouts.settings import bluetooth as bt
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(536, 240, "forget")
  gui_app._load_fonts()
  T = [100.0]
  bt.time = types.SimpleNamespace(monotonic=lambda: T[0])

  def phone(paired=True):
    return {"mac": PHONE, "name": "iPhone", "rssi": -60, "paired": paired, "connected": False, "dashkit": False}

  def step(page, status, dt=1.0):
    T[0] += dt
    FakeParams.store["DpbStatus"] = status
    FakeParams.store.pop("DpbCmd", None)  # btagentd took it
    page._update_state()
    b = next((w for w in page._scroller.items if isinstance(w, bt.DeviceButton) and w.mac == PHONE), None)
    if b is not None:
      b._update_state()
    return b

  def start(status):
    FakeParams.store = {}
    page = bt.BluetoothUIMici()
    b = step(page, status)
    b._forget()
    assert FakeParams.store["DpbCmd"] == f"forget:{PHONE}" and b.forgetting
    return page, step(page, status)

  out = {}
  page, b = start({"devices": [phone()]})
  out["forgetting"] = b.value
  out["gone"] = step(page, {"devices": []}) is None

  page, b = start({"devices": [phone()]})
  b = step(page, {"devices": [phone(False)]})
  out["unpaired"] = [b.forgetting, b.value]

  page, b = start({"devices": [phone()]})
  b = step(page, {"devices": [phone()], "error": "org.bluez.Error.Failed"}, 5)
  out["before_deadline"] = [b.forgetting, b.value]
  b = step(page, {"devices": [phone()], "error": "org.bluez.Error.Failed"}, 6)
  out["timeout_error"] = [b.forgetting, b.value]

  page, b = start({"devices": [phone()]})
  b = step(page, {"devices": [phone()]}, 11)
  out["timeout"] = [b.forgetting, b.value]
  print("RESULT " + json.dumps(out))
''')


@pytest.fixture(scope="module")
def result():
  if not os.environ.get("DISPLAY"):
    pytest.skip("needs a display (xvfb-run)")
  env = dict(os.environ, SCALE="1")
  r = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=120, env=env,
                     cwd=Path(__file__).resolve().parents[4])
  line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), None)
  assert line, r.stdout[-2000:] + r.stderr[-2000:]
  import json
  return json.loads(line[7:])


def test_forgetting_shows_while_waiting(result):
  assert result["forgetting"] == "forgetting..."


def test_forget_success_drops_the_row(result):
  assert result["gone"]


def test_forget_unpaired_clears_forgetting(result):
  assert result["unpaired"] == [False, "pair"]


def test_forget_timeout_shows_the_error(result):
  assert result["before_deadline"] == [True, "forgetting..."]
  assert result["timeout_error"] == [False, "forget failed: org.bluez.Error.Failed"]


def test_forget_timeout_without_error_recovers(result):
  assert result["timeout"] == [False, "paired"]
