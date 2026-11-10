"""Set Speed Assist shortcut on the mici Home Screen: shown only while the toggle is on with openpilot
longitudinal, sitting just left of the chestnut (Jetlink GPU link) icon. Renders the real MiciHomeLayout
offscreen in a child process, since ui_state has to be stubbed before home.py is imported."""
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
                       has_longitudinal_control=True, usb_connected=False, usb_unknown=False, chestnut_state=CS.READY,
                       recording_audio=False, is_body=False, CP=None,
                       sm=SM({"deviceState": SimpleNamespace(networkType=log.DeviceState.NetworkType.wifi,
                                                             networkStrength=SimpleNamespace(raw=3))}))
  mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mod.ui_state, mod.UIStatus, mod.ChestnutState, mod.device = ui, UIStatus, CS, SimpleNamespace(awake=True)
  sys.modules["openpilot.selfdrive.ui.ui_state"] = mod

  import raylib_nb as rl
  from openpilot.system.ui.lib.application import gui_app
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(536, 240, "ssa")
  gui_app._load_fonts()
  from openpilot.selfdrive.ui.mici.layouts import home

  out = {}
  for op_long in (True, False):
    for ssa in (True, False):
      for link in ("ready", "loading", "none"):
        for alerts in (0, 2):
          ui.has_longitudinal_control = op_long
          ui.chestnut_state = {"ready": CS.READY, "loading": CS.LOADING, "none": CS.NONE}[link]
          params.put_bool("SetSpeedAssist", ssa, block=True)
          clicks = []
          lay = home.MiciHomeLayout()
          lay.set_callbacks(on_set_speed_assist=lambda: clicks.append("ssa"), on_alerts=lambda: clicks.append("alerts"),
                            on_settings=lambda: clicks.append("settings"),
                            alert_count_callback=lambda a=alerts: a, alert_icon_callback=lambda: None)
          lay.set_rect(rl.Rectangle(0, 0, 536, 240))
          lay._update_state()
          tex = rl.load_render_texture(536, 240)
          rl.begin_texture_mode(tex)
          lay.render(rl.Rectangle(0, 0, 536, 240))
          rl.end_texture_mode()
          r = lambda w: [w.rect.x, w.rect.y, w.rect.width, w.rect.height] if w.is_visible else None
          link_w = next((w for w in (lay._chestnut_icon, lay._chestnut_loading_icon, lay._chestnut_failed_icon) if w.is_visible), None)
          h = lay._ssa_hit
          if h.width > 0:
            lay._handle_mouse_release(rl.Vector2(h.x + h.width / 2, h.y + h.height / 2))
          out[f"{int(op_long)}{int(ssa)}{link}{alerts}"] = dict(
            ssa=r(lay._ssa_icon), link=r(link_w) if link_w else None, pill=[lay._alerts_pill.rect.x, lay._alerts_pill.rect.width],
            long=r(lay._long_badge), hit=[h.x, h.y, h.width, h.height], clicks=clicks)
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


def test_hidden_unless_enabled_with_op_long(probe):
  for key, v in probe.items():
    shown = key.startswith("11")
    assert (v["ssa"] is not None) == shown, key
    assert (v["hit"][2] > 0) == shown, key
    assert v["clicks"] == (["ssa"] if shown else []), key


def test_sits_just_left_of_the_gpu_link(probe):
  for link in ("ready", "loading"):
    for alerts in (0, 2):
      v = probe[f"11{link}{alerts}"]
      ssa_x, _, ssa_w, _ = v["ssa"]
      assert v["link"] is not None
      assert ssa_x + ssa_w + 18 == v["link"][0]       # the row's spacing, then the link icon
      assert ssa_x == v["long"][0] + v["long"][2] + 18
      # the link icon moves right by exactly the shortcut's slot when it is shown
      assert v["link"][0] == probe[f"10{link}{alerts}"]["link"][0] + ssa_w + 18


def test_takes_the_link_slot_without_a_link(probe):
  for alerts in (0, 2):
    v, off = probe[f"11none{alerts}"], probe[f"10none{alerts}"]
    assert v["link"] is None and off["ssa"] is None
    assert v["ssa"][0] == v["long"][0] + v["long"][2] + 18
    assert probe[f"11none{alerts}"]["ssa"] == probe[f"11ready{alerts}"]["ssa"]   # same spot either way


def test_clear_of_the_alerts_pill(probe):
  for key, v in probe.items():
    if v["ssa"] is None:
      continue
    pill_x = v["pill"][0]
    assert v["hit"][0] + v["hit"][2] < pill_x, key
    if v["link"] is not None:
      assert v["link"][0] + v["link"][2] < pill_x, key
    assert v["ssa"][1] + v["ssa"][3] <= 240, key


def test_white_icon():
  from pathlib import Path
  svg = (Path(__file__).resolve().parents[3] / "assets/icons_mici/set_speed_assist.svg").read_text()
  assert "#FFFFFF" in svg and "#00FF40" not in svg
