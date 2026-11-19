# TITS steering alone draws the path, ball and compass like engaged; fully off dims like stock
import json
import os
import subprocess
import sys
import textwrap

import pytest

PROBE = textwrap.dedent('''
  import json, sys, types
  from types import SimpleNamespace
  # libparams_c.so isn't needed to draw, so a stand-in Params
  m = types.ModuleType("openpilot.common.params")
  class Params:
    def __init__(self, *a, **k): pass
    def get_bool(self, *a, **k): return False
    def get(self, *a, **k): return None
    def __getattr__(self, n): return lambda *a, **k: None
  m.Params = Params
  sys.modules["openpilot.common.params"] = m

  import raylib_nb as rl
  from openpilot.cereal import log, custom
  from openpilot.system.ui.lib.application import gui_app
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(536, 240, "tits")
  gui_app._load_fonts()
  print("WINDOW", flush=True)

  from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
  OP = log.SelfdriveState.OpenpilotState
  MS = custom.ModularAssistiveDrivingSystem.ModularAssistiveDrivingSystemState
  ss = SimpleNamespace(enabled=False, state=OP.disabled)
  mads = SimpleNamespace(enabled=False, active=False, available=True, state=MS.disabled)
  class SM(dict):
    frame = 10
    updated = {"selfdriveState": True, "carParams": False, "modelV2": False, "radarState": False}
    recv_frame = {"extrinsicsCalibration": 10, "modelV2": 10}
    valid = {"radarState": False}
    alive = {}
  sm = SM(selfdriveState=ss, selfdriveStateSP=SimpleNamespace(mads=mads), deviceState=SimpleNamespace(chestnutPresent=False),
          carOutput=SimpleNamespace(actuatorsOutput=SimpleNamespace(torque=0.0)),
          extrinsicsCalibration=SimpleNamespace(height=[1.22]),
          modelV2=SimpleNamespace(meta=SimpleNamespace(disengagePredictions=SimpleNamespace(brakeDisengageProbs=[0.1], steerOverrideProbs=[0.1]))))
  ui_state.sm = sm
  ui_state.started = ui_state._started_prev = True
  ui_state.started_frame = 0

  from openpilot.selfdrive.ui.mici.onroad import status, model_renderer, confidence_ball, hud_renderer as hm
  from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer
  from openpilot.selfdrive.ui.mici.onroad.confidence_ball import ConfidenceBall
  T = [100.0]
  rl.get_time = lambda: T[0]
  hm.custom_onroad_ui = lambda: True
  hm.compass_size = lambda: hm.COMPASS_LARGE
  hm.heading_letter, hm.heading_deg = (lambda: "N"), (lambda: 0.0)

  seen = {}
  mr = ModelRenderer()
  mr._longitudinal_control, mr._transform_dirty = True, False
  mr._draw_lane_lines = lambda: None
  mr._draw_path = lambda: seen.__setitem__("path", mr._visible)
  ball = ConfidenceBall()
  RECT = rl.Rectangle(72, 0, 464, 240)
  ball.set_rect(RECT)
  confidence_ball.draw_circle_gradient = lambda x, y, r, top, bottom, a: seen.__setitem__("ball", (y, [top.r, top.g, top.b]))
  hud = hm.HudRenderer()
  bg = hud._txt_compass_bg90.id
  _dte = rl.draw_texture_ex
  def dte(tex, *a):
    if tex.id == bg:
      seen["compass"] = a[-1].a
    return _dte(tex, *a)
  rl.draw_texture_ex = dte

  def run(n=150):
    for _ in range(n):
      seen.clear()
      sm.frame += 1
      T[0] += 1 / gui_app.target_fps
      ui_state._update_status()
      rl.begin_drawing()
      mr._render(RECT)
      ball._confidence_filter.x = 0.8
      ball._render(RECT)
      hud.set_can_draw_top_icons(True)
      hud._draw_compass(RECT)
      stock = status.status_fade.weight(UIStatus.DISENGAGED)
      ll = mr._get_ll_color(0.7, True, False)
      rl.end_drawing()
    return {"status": ui_state.status.value, "steer": ui_state.steer_status.value, "stock_fade": stock,
            "path": seen.get("path", 0.0), "ball": seen.get("ball"), "compass": seen.get("compass", 0), "lane": [ll.r, ll.g, ll.b]}

  out = {}
  ss.enabled, ss.state = True, OP.enabled
  out["engaged"] = run()
  ss.enabled, ss.state = False, OP.disabled
  mads.enabled, mads.active, mads.state = True, True, MS.enabled
  out["tits"] = run()
  # going offroad resets it, the next frame doesn't recompute while stopped
  ui_state.started = False
  ui_state._update_status()
  out["offroad_steer"] = ui_state.steer_status.value
  ui_state.started = True
  run(1)
  ui_state.started_frame = 0  # keep the fake model data current
  mads.state = MS.overriding
  out["tits_override"] = run()
  mads.active, mads.state = False, MS.paused
  out["paused"] = run()
  mads.enabled, mads.state = False, MS.disabled
  out["off"] = run()
  # long only: openpilot engaged, TITS paused
  ss.enabled, ss.state = True, OP.enabled
  mads.enabled, mads.state = True, MS.paused
  out["long_only"] = run()
  print("RESULT" + json.dumps(out))
''')


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
  env = dict(os.environ, PARAMS_ROOT=str(tmp_path_factory.mktemp("params")))
  p = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, timeout=120)
  if "WINDOW" not in p.stdout:
    pytest.skip(f"no raylib window here: {p.stderr[-400:]}")
  line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT")), None)
  assert line, p.stderr[-2000:]
  return json.loads(line[6:])


def test_steering_only_looks_engaged(probe):
  eng, tits = probe["engaged"], probe["tits"]
  assert tits["status"] == "disengaged" and tits["steer"] == "engaged"
  assert tits["path"] > 0.99 and tits["compass"] >= 225
  assert tits["ball"][0] == pytest.approx(eng["ball"][0], abs=0.5) and tits["ball"][1] == eng["ball"][1]  # same height, engaged colors
  assert tits["lane"] == eng["lane"] != probe["off"]["lane"]  # lane lines in the engaged color


def test_long_only_stays_lit(probe):
  s = probe["long_only"]
  assert s["status"] == "engaged" and s["steer"] == "engaged"
  assert s["path"] > 0.99 and s["compass"] >= 225 and s["stock_fade"] < 0.01


def test_offroad_resets_steer_status(probe):
  assert probe["offroad_steer"] == "disengaged"


def test_steering_only_leaves_the_rest_disengaged(probe):
  # MAX, personality, wheel, camera keep reading the stock status
  assert probe["tits"]["stock_fade"] > 0.99


def test_tits_override_is_white(probe):
  assert probe["tits_override"]["steer"] == "override"
  assert probe["tits_override"]["path"] > 0.99
  assert probe["tits_override"]["ball"][1] == [255, 255, 255]


@pytest.mark.parametrize("state", ["paused", "off"])
def test_no_steering_dims_like_stock(probe, state):
  s, eng = probe[state], probe["engaged"]
  assert s["steer"] == "disengaged"
  assert s["path"] == 0.0 and s["compass"] == 0
  assert s["ball"][0] > eng["ball"][0] and s["ball"][1] == [102, 102, 102]  # rests at the bottom, grey
