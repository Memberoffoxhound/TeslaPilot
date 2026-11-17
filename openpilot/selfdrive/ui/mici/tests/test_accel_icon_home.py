"""Accelerator icon on the mici Home Screen: fills while provisioning, orange only on failure, tap opens Models."""
import json
import os
import subprocess
import sys
import textwrap

import pytest

PROBE = textwrap.dedent('''
  import json, sys, types
  from enum import Enum
  from types import SimpleNamespace
  from openpilot.common.params import Params
  from openpilot.cereal import log

  params = Params()
  CS = SimpleNamespace(NONE=0, LOADING=1, WAITING=2, READY=3, ACTIVE=4, UNCOMPILED=5, FAILED=6)
  class UIStatus(Enum):
    DISENGAGED = 0
  class SM(dict):
    updated = {}
  ui = SimpleNamespace(started=False, is_metric=False, params=params, status=UIStatus.DISENGAGED, engaged=False,
                       has_longitudinal_control=False, usb_connected=True, usb_unknown=False, chestnut_state=CS.READY,
                       recording_audio=False, is_body=False, CP=None, accel_progress=None,
                       sm=SM({"deviceState": SimpleNamespace(networkType=log.DeviceState.NetworkType.wifi,
                                                             networkStrength=SimpleNamespace(raw=3))}))
  mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mod.ui_state, mod.UIStatus, mod.ChestnutState, mod.device = ui, UIStatus, CS, SimpleNamespace(awake=True)
  sys.modules["openpilot.selfdrive.ui.ui_state"] = mod

  import raylib_nb as rl
  from openpilot.system.ui.lib.application import gui_app
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(536, 240, "accel")
  gui_app._load_fonts()
  from openpilot.selfdrive.ui.mici.layouts import home

  out = {}
  cases = {"ready": (CS.READY, None), "first_download": (CS.UNCOMPILED, ("download", 0.3)),
           "compile": (CS.READY, ("compile", None)), "uncompiled": (CS.UNCOMPILED, None), "failed": (CS.FAILED, None),
           "none": (CS.NONE, None)}
  for name, (state, progress) in cases.items():
    ui.chestnut_state, ui.accel_progress = state, progress
    clicks = []
    lay = home.MiciHomeLayout()
    lay.set_callbacks(on_models=lambda: clicks.append("models"), on_settings=lambda: clicks.append("settings"),
                      alert_count_callback=lambda: 0, alert_icon_callback=lambda: None)
    lay.set_rect(rl.Rectangle(0, 0, 536, 240))
    lay._update_state()
    tex = rl.load_render_texture(536, 240)
    rl.begin_texture_mode(tex)
    lay.render(rl.Rectangle(0, 0, 536, 240))
    rl.end_texture_mode()
    h = lay._accel_hit
    if h.width > 0:
      lay._handle_mouse_release(rl.Vector2(h.x + h.width / 2, h.y + h.height / 2))
    out[name] = dict(fill=lay._chestnut_fill_icon.is_visible, failed=lay._chestnut_failed_icon.is_visible,
                     ready=lay._chestnut_icon.is_visible, usb=lay._usb_icon.is_visible, clicks=clicks)
  print("RESULT" + json.dumps(out))
''')


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
  env = dict(os.environ, PARAMS_ROOT=str(tmp_path_factory.mktemp("params")))
  p = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, timeout=120)
  line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT")), None)
  if line is None:
    pytest.skip(f"no raylib window here: {p.stderr[-400:]}")
  return json.loads(line[6:])


def test_fills_while_provisioning_not_orange(probe):
  for name in ("first_download", "compile"):
    assert probe[name]["fill"] and not probe[name]["failed"] and not probe[name]["ready"], name


def test_orange_only_for_real_failures(probe):
  assert probe["failed"]["failed"] and probe["uncompiled"]["failed"]
  assert not probe["ready"]["failed"] and probe["ready"]["ready"] and not probe["ready"]["fill"]


def test_tap_opens_models(probe):
  for name in ("ready", "first_download", "compile", "failed"):
    assert probe[name]["clicks"] == ["models"], name
  assert probe["none"]["clicks"] == []
