# our onroad elements fade with comma's status_fade: compasses, gpu icon, MAX under the ball
import json
import os
import subprocess
import sys
import textwrap

import pytest

HEAD = textwrap.dedent('''
  import json, sys, types
  from enum import Enum
  from types import SimpleNamespace

  class UIStatus(Enum):
    DISENGAGED = "disengaged"
    ENGAGED = "engaged"
    OVERRIDE = "override"
  class CS(Enum):
    DISCONNECTED, UNCOMPILED, READY, LOADING, ACTIVE, FAILED, WAITING = range(7)
  ss = SimpleNamespace(enabled=True, personality=SimpleNamespace(raw=1), alertSize=0)
  car = SimpleNamespace(vCruiseCluster=105, vEgoCluster=29.0, vEgo=29.0, steeringAngleDeg=0.0)
  class SM(dict):
    frame, recv_frame, alive = 1, {"carState": 10, "selfdriveState": 10}, {"longitudinalPlan": False}
  sm = SM(selfdriveState=ss, carState=car, longitudinalPlan=SimpleNamespace(hasLead=False))
  from openpilot.common.params import Params
  ui = SimpleNamespace(sm=sm, params=Params(), status=UIStatus.ENGAGED, engaged=True, started=True, started_frame=0, is_metric=False,
                       chestnut_state=CS.ACTIVE, accel_progress=None, has_longitudinal_control=True)
  mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mod.ui_state, mod.UIStatus, mod.ChestnutState = ui, UIStatus, CS
  sys.modules["openpilot.selfdrive.ui.ui_state"] = mod

  import raylib_nb as rl
  from openpilot.system.ui.lib.application import gui_app
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(536, 240, "fade")
  gui_app._load_fonts()
  print("WINDOW", flush=True)
  T = [100.0]
  rl.get_time = lambda: T[0]
  from openpilot.selfdrive.ui.mici.onroad import hud_renderer as hm
  S = {"custom": True, "size": 1}
  hm.custom_onroad_ui = lambda: S["custom"]
  hm.compass_size = lambda: S["size"]
  hm.heading_letter, hm.heading_deg = (lambda: "NW"), (lambda: 312.0)
  hud = hm.HudRenderer()
  hud._torque_bar.render = lambda r: None
  names = {hud._txt_chestnut_green.id: "gpu", hud._txt_chestnut_orange.id: "gpu", hud._txt_chestnut.id: "gpu",
           hud._txt_compass_bg90.id: "compass", hud._txt_compass_bg.id: "compass"}
  seen = {}
  def rec(f):
    def w(tex, *a):
      n = names.get(tex.id)
      if n and n not in seen:  # first draw of each, its alpha and position
        pos = a[0] if isinstance(a[0], rl.Vector2) else a[1]
        seen[n] = (a[-1].a, round(pos.x), round(pos.y))
      return f(tex, *a)
    return w
  rl.draw_texture_ex, rl.draw_texture_pro = rec(rl.draw_texture_ex), rec(rl.draw_texture_pro)
  RECT, PANEL = rl.Rectangle(72, 0, 464, 240), rl.Rectangle(0, 0, 72, 240)

  def frames(n=1, status=None, top=True, **kw):
    if status is not None:
      ui.status, ui.engaged, ss.enabled = status, status != UIStatus.DISENGAGED, status != UIStatus.DISENGAGED
    for k, v in kw.items():
      setattr(ui, k, v)
    for _ in range(n):
      seen.clear()
      sm.frame += 1
      T[0] += 1 / gui_app.target_fps
      hud.set_can_draw_top_icons(top)
      hud._update_state()
      hud._chestnut_fade_time = T[0]  # hold the transient icon up
      rl.begin_drawing()
      hud.render(RECT)
      hud.render_small_compass(PANEL, True)
      rl.end_drawing()
    return {k: v[0] for k, v in seen.items()}

  def pos(name):
    return seen[name][1:] if name in seen else None
''')

FADE = textwrap.dedent('''
  out = {}
  frames(120, UIStatus.ENGAGED)
  out["engaged"] = frames()
  out["max_engaged"] = hud.set_speed_alpha()
  mid = frames(6, UIStatus.DISENGAGED)
  out["mid"], out["max_mid"] = mid, hud.set_speed_alpha()
  frames(240)
  out["disengaged"] = frames()
  out["max_disengaged"] = hud.set_speed_alpha()
  frames(240, UIStatus.ENGAGED, top=False)
  out["alert"] = frames(top=False)
  S["size"] = 0
  frames(240, UIStatus.ENGAGED)
  out["small_engaged"] = frames()
  frames(240, UIStatus.DISENGAGED)
  out["small_disengaged"] = frames()
  S["custom"] = False
  frames(240, UIStatus.DISENGAGED, top=False)
  out["stock_disengaged_alert"] = frames(top=False)
  print("RESULT" + json.dumps(out))
''')


def run_probe(tmp_path_factory, body):
  env = dict(os.environ, PARAMS_ROOT=str(tmp_path_factory.mktemp("params")))
  p = subprocess.run([sys.executable, "-c", HEAD + body], capture_output=True, text=True, env=env, timeout=120)
  line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT")), None)
  if "WINDOW" not in p.stdout:
    pytest.skip(f"no raylib window here: {p.stderr[-400:]}")
  assert line, p.stderr[-2000:]
  return json.loads(line[6:])


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
  return run_probe(tmp_path_factory, FADE)


def test_large_compass_fades_like_max(probe):
  assert probe["engaged"]["compass"] >= 225
  assert 0.5 < probe["mid"]["compass"] / probe["engaged"]["compass"] < 0.8   # status_fade's pace, 0.1 s in
  assert "compass" not in probe["disengaged"] and "compass" not in probe["alert"]


def test_small_compass_dims_like_panel_icons(probe):
  assert probe["small_engaged"]["compass"] >= 225
  assert 75 <= probe["small_disengaged"]["compass"] <= 88   # DIMMED_ICON_ALPHA


def test_gpu_icon_dims_and_hides_under_alerts(probe):
  assert probe["engaged"]["gpu"] >= 250
  assert 75 <= probe["disengaged"]["gpu"] <= 88
  assert "gpu" not in probe["alert"]
  assert probe["stock_disengaged_alert"]["gpu"] >= 250  # custom ui off stays stock


def test_max_alpha_follows_status_fade(probe):
  assert probe["max_engaged"] > 0.9 and probe["max_disengaged"] < 0.01
  assert 0.5 < probe["max_mid"] < 0.8   # what the ball's left-side occlusion reads
