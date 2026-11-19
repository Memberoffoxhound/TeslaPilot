# TITS steering alone: lane lines and path trade colors, with a fade
import json
import os
import subprocess
import sys
import textwrap

import pytest

PROBE = textwrap.dedent('''
  import json, sys, types
  from types import SimpleNamespace
  import numpy as np
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
  rl.init_window(536, 240, "swap")
  print("WINDOW", flush=True)

  from openpilot.selfdrive.ui.ui_state import ui_state
  OP = log.SelfdriveState.OpenpilotState
  MS = custom.ModularAssistiveDrivingSystem.ModularAssistiveDrivingSystemState
  ss = SimpleNamespace(enabled=False, state=OP.disabled)
  mads = SimpleNamespace(enabled=False, active=False, available=True, state=MS.disabled)
  class SM(dict):
    frame = 10
    updated = {"selfdriveState": True, "carParams": False, "modelV2": False, "radarState": False}
    recv_frame = {"extrinsicsCalibration": 10, "modelV2": 10}
    valid = {"radarState": False}
  ui_state.sm = SM(selfdriveState=ss, selfdriveStateSP=SimpleNamespace(mads=mads),
                   carOutput=SimpleNamespace(actuatorsOutput=SimpleNamespace(torque=0.0)),
                   extrinsicsCalibration=SimpleNamespace(height=[1.22]), modelV2=None)
  ui_state.started = ui_state._started_prev = True
  ui_state.started_frame = 0

  from openpilot.selfdrive.ui.mici.onroad import model_renderer as mrm
  mrm.custom_onroad_ui = lambda: False
  mr = mrm.ModelRenderer()
  mr._longitudinal_control, mr._transform_dirty = False, False
  mr._path.projected_points = np.array([[0, 0], [10, 0], [10, 10]], dtype=np.float32)
  mr._draw_lane_lines = lambda: None
  seen = {}
  def poly(rect, pts, color=None, gradient=None):
    seen["path"] = [[c.r, c.g, c.b, c.a] for c in gradient.colors] if gradient else [[color.r, color.g, color.b, color.a]]
  mrm.draw_polygon = poly
  RECT = rl.Rectangle(0, 0, 536, 240)

  T = [100.0]
  rl.get_time = lambda: T[0]  # status fade's override hold reads the clock

  def frame():
    ui_state.sm.frame += 1
    T[0] += 1 / gui_app.target_fps
    ui_state._update_status()
    mr._render(RECT)
    ll = mr._get_ll_color(0.7, True, False)
    return {"swap": mr._swap.x, "lane": [ll.r, ll.g, ll.b], "path": seen["path"]}

  def run(n):
    return [frame() for _ in range(n)]

  fps = gui_app.target_fps
  out = {"fps": fps, "stock": [[c.r, c.g, c.b, c.a] for c in mrm.STOCK_PATH_GRADIENT.colors], "ll": [0, 255, 64]}
  ss.enabled, ss.state = True, OP.enabled
  out["engaged_off"] = run(fps)[-1]  # TITS off
  mads.enabled, mads.active, mads.state = True, True, MS.enabled
  out["engaged"] = run(fps)[-1]  # TITS on and openpilot engaged
  ss.enabled, ss.state = False, OP.disabled
  out["enter"] = run(fps)  # cruise cancel: steering only
  mads.state = MS.overriding
  out["override"] = run(fps)[-1]
  mads.state = MS.enabled
  run(fps)
  ss.enabled, ss.state = True, OP.enabled
  out["leave"] = run(fps)  # cruise back on
  # plain white path (long, no gradient yet)
  mr._longitudinal_control = True
  ss.enabled, ss.state = False, OP.disabled
  out["plain"] = run(fps)[-1]
  # driver torque near the threshold: TITS override flaps 2 of every 6 frames
  flap = []
  for i in range(fps):
    mads.state = MS.overriding if i % 6 < 2 else MS.enabled
    flap.append(frame())
  out["flap"] = flap
  mads.state = MS.enabled
  # Tesla theme, openpilot long gradient
  mrm.custom_onroad_ui, mrm.tesla_theme = (lambda: True), (lambda: True)
  long_grad = mrm.Gradient(start=(0.0, 1.0), end=(0.0, 0.0), colors=[rl.Color(242, 242, 242, 102), rl.Color(200, 230, 120, 60),
                                                                     rl.Color(164, 255, 61, 0)], stops=[0.0, 0.4, 0.7])
  mr._path_gradient = long_grad
  out["long_grad"] = [[c.r, c.g, c.b, c.a] for c in long_grad.colors]
  out["tesla_steer"] = run(2 * fps)[-1]
  ss.enabled, ss.state = True, OP.enabled
  out["tesla_engaged"] = run(fps)[-1]
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


def test_engaged_unchanged(probe):
  for s in (probe["engaged_off"], probe["engaged"]):
    assert s["swap"] == 0.0 and s["lane"] == probe["ll"] and s["path"] == probe["stock"]


def test_steering_only_swaps(probe):
  s, stock = probe["enter"][-1], probe["stock"]
  assert s["lane"] == stock[0][:3]  # the path's most opaque stop
  assert [c[:3] for c in s["path"]] == [probe["ll"]] * len(stock)  # lane color, same stops
  assert [c[3] for c in s["path"]] == [c[3] for c in stock]  # alpha kept


def test_swap_fades_both_ways(probe):
  fps = probe["fps"]
  for frames, up in ((probe["enter"], True), (probe["leave"], False)):
    sw = [f["swap"] for f in frames]
    assert all(b > a for a, b in zip(sw, sw[1:], strict=False)) if up else all(b < a for a, b in zip(sw, sw[1:], strict=False))
    tenth = sw[fps // 10 - 1]
    assert 0.3 < (tenth if up else 1 - tenth) < 0.7  # partway after 0.1 s
    half = sw[fps // 2 - 1]
    assert half > 0.95 if up else half < 0.05  # about done by 0.5 s
    mid = frames[fps // 10 - 1]
    assert mid["lane"] not in (probe["ll"], probe["stock"][0][:3])  # blended, not snapped
  assert probe["leave"][-1]["path"] == probe["stock"] and probe["leave"][-1]["lane"] == probe["ll"]


def test_override_stays_white(probe):
  assert probe["override"]["lane"] == [255, 255, 255]


def test_plain_path_takes_lane_color(probe):
  s = probe["plain"]
  assert s["path"][0][:3] == probe["ll"] and s["lane"] == [255, 255, 255]


def test_override_flapping_does_not_pulse(probe):
  flap = probe["flap"]
  assert min(f["swap"] for f in flap) > 0.99
  assert all(f["path"] == flap[0]["path"] for f in flap)  # path color steady


def test_tesla_long_gradient_tinted(probe):
  blue, grad = [62, 140, 235], probe["long_grad"]
  s = probe["tesla_steer"]
  assert [c[:3] for c in s["path"]] == [blue] * len(grad) and [c[3] for c in s["path"]] == [c[3] for c in grad]
  assert s["lane"] == grad[0][:3]  # most opaque stop
  e = probe["tesla_engaged"]
  assert e["path"] == grad and e["lane"] == blue
