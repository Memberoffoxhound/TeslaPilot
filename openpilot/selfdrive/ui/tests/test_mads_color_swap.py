# MADS steering alone: lane lines and path trade colors, with a fade
import json
import os
import subprocess
import sys
import textwrap

import pytest

from openpilot.conftest import PARAMS_PROBE_STUB

WHITE = [242, 242, 242]
LANES = [(40, 200), (120, 230), (416, 306), (500, 340)]  # probe lane lines: near x, far x


def brighter(path, base):
  # alpha x1.5, within rounding of a swap still a hair under 1
  return all(abs(p[3] - min(255, c[3] * 1.5)) <= 1 for p, c in zip(path, base, strict=True))

PROBE = textwrap.dedent('''
  import json, sys, types
  from types import SimpleNamespace
  import numpy as np
  {PARAMS_PROBE_STUB}

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
  # path: left edge near to far, then right edge far to near
  PATH = np.array([[200, 240], [260, 100], [276, 100], [336, 240]], dtype=np.float32)
  mr._path.projected_points = PATH
  # 4 lane lines (near x, far x), 6 px wide near, no road edges
  LANES = [(40, 200), (120, 230), (416, 306), (500, 340)]
  mr._lane_lines = [SimpleNamespace(projected_points=np.array([[n - 3, 240], [f - 1, 100], [f + 1, 100], [n + 3, 240]], dtype=np.float32))
                    for n, f in LANES]
  mr._lane_line_probs, mr._road_edges = np.full(4, 0.7), []
  seen = {}
  def poly(rect, pts, color=None, gradient=None):
    if np.array_equal(pts, PATH):
      seen["path"] = [[c.r, c.g, c.b, c.a] for c in gradient.colors] if gradient else [[color.r, color.g, color.b, color.a]]
    else:  # near center x, near width, alpha, rgb
      seen.setdefault("lanes", []).append([float(pts[0, 0] + pts[-1, 0]) / 2, float(abs(pts[-1, 0] - pts[0, 0])), color.a,
                                           [color.r, color.g, color.b]])
  mrm.draw_polygon = poly
  RECT = rl.Rectangle(0, 0, 536, 240)

  T = [100.0]
  rl.get_time = lambda: T[0]  # status fade's override hold reads the clock

  def frame():
    seen.clear()
    ui_state.sm.frame += 1
    T[0] += 1 / gui_app.target_fps
    ui_state._update_status()
    mr._render(RECT)
    ll = mr._get_ll_color(0.7, True, False)
    lanes = seen.get("lanes", [])
    return {"swap": mr._swap.x, "lane": [ll.r, ll.g, ll.b], "path": seen["path"], "lanes": lanes,
            "lane_a": max((ln[2] for ln in lanes), default=0)}

  def run(n):
    return [frame() for _ in range(n)]

  fps = gui_app.target_fps
  out = {"fps": fps, "stock": [[c.r, c.g, c.b, c.a] for c in mrm.STOCK_PATH_GRADIENT.colors], "ll": [0, 255, 64]}
  ss.enabled, ss.state = True, OP.enabled
  out["engaged_off"] = run(fps)[-1]  # MADS off
  mads.enabled, mads.active, mads.state = True, True, MS.enabled
  out["engaged"] = run(fps)[-1]  # MADS on and openpilot engaged
  ss.enabled, ss.state = False, OP.disabled
  out["enter"] = run(fps)  # cruise cancel: steering only
  mads.state = MS.overriding
  out["override"] = run(fps)[-1]
  mads.state = MS.enabled
  run(fps)
  ss.enabled, ss.state = True, OP.enabled
  out["leave"] = run(2 * fps)  # cruise back on
  # plain white path (long, no gradient yet)
  mr._longitudinal_control = True
  ss.enabled, ss.state = False, OP.disabled
  out["plain"] = run(fps)[-1]
  # driver torque near the threshold: MADS override flaps 2 of every 6 frames
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
  # speeding up (green) and braking (red) paths
  for key, rgb in (("speed_up", (164, 255, 61)), ("braking", (255, 61, 61))):
    mr._path_gradient = mrm.Gradient(start=(0.0, 1.0), end=(0.0, 0.0), colors=[rl.Color(*rgb, 102), rl.Color(*rgb, 0)], stops=[0.0, 0.7])
    out[key] = run(fps // 4)[-1]
  mr._path_gradient = long_grad
  ss.enabled, ss.state = True, OP.enabled
  out["tesla_engaged"] = run(fps)[-1]
  print("RESULT" + json.dumps(out))
''').replace("{PARAMS_PROBE_STUB}", PARAMS_PROBE_STUB)


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
    assert [ln[:3] for ln in s["lanes"]] == [[n, 6.0, 178] for n, _ in LANES]  # lane lines as today


def test_steering_only_swaps(probe):
  s, stock = probe["enter"][-1], probe["stock"]
  assert s["lane"] == WHITE  # fixed near-white, not the path color
  assert [c[:3] for c in s["path"]] == [probe["ll"]] * len(stock)  # lane color, same stops
  assert brighter(s["path"], stock)


def test_steering_only_lanes_become_border(probe):
  outer_l, left, right, outer_r = probe["enter"][-1]["lanes"]
  assert outer_l[2] == 0 and outer_r[2] == 0  # the far lines fade out
  for ln, edge_x in ((left, 200), (right, 336)):  # path edges, near end
    x, width, a, rgb = ln
    assert abs(x - edge_x) < 0.5 and abs(width - 3.0) < 0.05 and abs(a - 178) <= 1 and rgb == WHITE


def test_lanes_slide_in_mid_fade(probe):
  fps = probe["fps"]
  for frames in (probe["enter"], probe["leave"]):
    mid = frames[fps // 10 - 1]["lanes"]
    (lx, lw, _, _), (rx, rw, _, _) = mid[1], mid[2]
    assert 120 < lx < 200 and 336 < rx < 416  # between the lane and the path edge
    assert 3.0 < lw < 6.0 and 3.0 < rw < 6.0  # thinning toward the border

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
    assert mid["lane"] not in (probe["ll"], WHITE)  # blended, not snapped
    a, base = mid["path"][0][3], probe["stock"][0][3]
    assert base < a < round(base * 1.5)  # brightness ramps with the swap
    assert 0 < mid["lanes"][0][2] < 178  # far lines partway out
  assert probe["leave"][-1]["path"] == probe["stock"] and probe["leave"][-1]["lane"] == probe["ll"]
  assert [ln[:3] for ln in probe["leave"][-1]["lanes"]] == [[n, 6.0, 178] for n, _ in LANES]


def test_override_stays_white(probe):
  assert probe["override"]["lane"] == [255, 255, 255]


def test_plain_path_takes_lane_color(probe):
  s = probe["plain"]
  assert s["path"][0][:3] == probe["ll"] and s["path"][0][3] == 45 and s["lane"] == WHITE


def test_override_flapping_does_not_pulse(probe):
  flap = probe["flap"]
  assert min(f["swap"] for f in flap) > 0.99
  assert all(f["path"] == flap[0]["path"] for f in flap)  # path color steady


def test_tesla_long_gradient_tinted(probe):
  blue, grad = [62, 140, 235], probe["long_grad"]
  s = probe["tesla_steer"]
  assert [c[:3] for c in s["path"]] == [blue] * len(grad) and brighter(s["path"], grad)
  assert s["lane"] == WHITE
  e = probe["tesla_engaged"]
  assert e["path"] == grad and e["lane"] == blue


def test_lanes_stay_white_with_accel_colors(probe):
  for key in ("speed_up", "braking"):
    assert probe[key]["lane"] == WHITE and probe[key]["path"][0][:3] == [62, 140, 235]
