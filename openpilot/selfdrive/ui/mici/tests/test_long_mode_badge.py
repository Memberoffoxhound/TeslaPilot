"""LongModeBadge: make-based stock icon + OEM label; comma+LONG when OP long."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ARTIFACTS = Path("/workspace/artifacts/long_icon")

PROBE = textwrap.dedent('''
  import json, sys, types
  from enum import Enum
  from pathlib import Path
  from types import SimpleNamespace
  from PIL import Image
  from openpilot.common.params import Params
  from openpilot.cereal import log
  import raylib_nb as rl

  out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
  params = Params()
  for k, v in {"Version": "0.11.23", "GitBranch": "Highland-Dev-sweep",
               "GitCommit": "deadbeef", "GitCommitDate": "'0 2026'"}.items():
    params.put(k, v, block=True)

  CS = SimpleNamespace(NONE=0, LOADING=1, WAITING=2, READY=3, ACTIVE=4, UNCOMPILED=5, FAILED=6)
  class UIStatus(Enum):
    DISENGAGED = 0
  class SM(dict):
    updated = {}
  ui = SimpleNamespace(started=False, is_metric=False, params=params, status=UIStatus.DISENGAGED, engaged=False,
                       has_longitudinal_control=False, usb_connected=False, usb_unknown=False, chestnut_state=CS.NONE,
                       recording_audio=False, is_body=False, CP=None,
                       sm=SM({"deviceState": SimpleNamespace(networkType=log.DeviceState.NetworkType.wifi,
                                                             networkStrength=SimpleNamespace(raw=3))}))
  mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mod.ui_state, mod.UIStatus, mod.ChestnutState, mod.device = ui, UIStatus, CS, SimpleNamespace(awake=True)
  sys.modules["openpilot.selfdrive.ui.ui_state"] = mod

  from openpilot.system.ui.lib.application import gui_app
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(536, 240, "badge")
  gui_app._load_fonts()
  # match gui_app.init_window: measure_text_cached and draw_text_ex both use FONT_SCALE
  from openpilot.system.ui.lib.application import FONT_SCALE
  if not hasattr(rl, "_orig_draw_text_ex"):
    rl._orig_draw_text_ex = rl.draw_text_ex
    def _draw_text_ex_scaled(font, text, position, font_size, spacing, tint):
      return rl._orig_draw_text_ex(font, text, position, font_size * FONT_SCALE, spacing, tint)
    rl.draw_text_ex = _draw_text_ex_scaled
  from openpilot.selfdrive.ui.mici.layouts import home
  from openpilot.selfdrive.ui import tripstats
  tripstats.view = lambda p: {"today_m": 0, "today_e": 0, "week_m": 0, "week_e": 0}

  def cp(brand, fp=""):
    return SimpleNamespace(brand=brand, carFingerprint=fp)

  def save_tex(tex, path):
    img = rl.load_image_from_texture(tex.texture)
    raw = img.to_bytes(img.width * img.height * 4)
    Image.frombytes("RGBA", (img.width, img.height), raw).transpose(Image.FLIP_TOP_BOTTOM).save(path)
    rl.unload_image(img)

  cases = [
    ("op_long", True, cp("tesla", "TESLA_MODEL_3")),
    ("tesla_tacc", False, cp("tesla", "TESLA_MODEL_3")),
    ("kia_scc", False, cp("hyundai", "KIA_K5_2021")),
    ("generic_acc", False, cp("toyota", "TOYOTA_COROLLA")),
    ("hyundai_generic", False, cp("hyundai", "HYUNDAI_SONATA")),
  ]
  out = {}
  for name, op, car in cases:
    ui.has_longitudinal_control = op
    ui.CP = car
    badge = home.LongModeBadge()
    badge._update_state()
    w, h = int(badge.rect.width), int(badge.rect.height)
    pad = 8
    tw, th = w + pad * 2, h + pad * 2
    tex = rl.load_render_texture(tw, th)
    rl.begin_texture_mode(tex)
    rl.clear_background(rl.Color(20, 20, 20, 255))
    badge.set_rect(rl.Rectangle(pad, pad, float(w), float(h)))
    badge.render(rl.Rectangle(pad, pad, float(w), float(h)))
    rl.end_texture_mode()
    if out_dir is not None:
      out_dir.mkdir(parents=True, exist_ok=True)
      save_tex(tex, out_dir / f"badge_{name}.png")
    out[name] = {
      "width": w, "height": h,
      "op": op,
      "make": badge._make_name,
      "label": "LONG" if op else badge._make.stock_label,
      "text_rows": list(badge._make.text_rows) if (not op and badge._make.text_rows) else None,
      "logo_w": badge._logo_w,
      "letter_sz": badge._make.letter_sz,
    }
  print("RESULT" + json.dumps(out))
''')


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
  ARTIFACTS.mkdir(parents=True, exist_ok=True)
  env = dict(os.environ, PARAMS_ROOT=str(tmp_path_factory.mktemp("params")))
  p = subprocess.run([sys.executable, "-c", PROBE, str(ARTIFACTS)], capture_output=True, text=True, env=env, timeout=120)
  line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT")), None)
  if line is None:
    pytest.skip(f"no raylib window here: {p.stderr[-500:]}")
  return json.loads(line[6:])


def test_op_long_is_comma_long(probe):
  v = probe["op_long"]
  assert v["label"] == "LONG" and v["make"] == "tesla"
  assert v["width"] == 30 + 4 + 16  # matches generic 50px text badge


def test_tesla_stock(probe):
  v = probe["tesla_tacc"]
  assert v["make"] == "tesla" and v["label"] == "TACC"
  assert v["width"] == 48 + 4 + 16
  assert (ARTIFACTS / "badge_tesla_tacc.png").is_file()


def test_kia_stock(probe):
  v = probe["kia_scc"]
  assert v["make"] == "kia" and v["label"] == "SCC"
  assert v["width"] == 120 + 4 + 22
  assert v["letter_sz"] == 22
  assert probe["tesla_tacc"]["letter_sz"] == 11
  assert (ARTIFACTS / "badge_kia_scc.png").is_file()


def test_generic_stock_text_icon(probe):
  for key in ("generic_acc", "hyundai_generic"):
    v = probe[key]
    assert v["make"] == "generic" and v["label"] == "ACC"
    assert v["text_rows"] == ["STOCK", "ACC"]
    assert v["width"] == 50  # text icon only; no side OEM letters (STOCK/ACC fit-to-slot)
  assert (ARTIFACTS / "badge_generic_acc.png").is_file()
