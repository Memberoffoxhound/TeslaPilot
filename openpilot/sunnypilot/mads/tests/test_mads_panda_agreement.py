# MADS_MAIN_REPORTED and MADS_BUTTON_BRANDS are hand copies of what panda safety reads; check them against the safety sources
import re
from pathlib import Path

import pytest

from opendbc.car.car_helpers import interfaces
from opendbc.car.values import PLATFORMS
import opendbc.safety
from openpilot.sunnypilot.mads.helpers import mads_has_button, mads_main_reported

SAFETY_DIR = Path(opendbc.safety.__file__).parent
MODES_DIR = SAFETY_DIR / "modes"


def _code(path: Path) -> str:
  # C source without comments, so a commented-out writer doesn't count
  return re.sub(r"//[^\n]*|/\*.*?\*/", "", path.read_text(), flags=re.DOTALL)


def _hooks_header(safety_model: int) -> list[str]:
  # safetyModel number -> SAFETY_ id -> hooks struct -> mode header, plus the mode headers it includes
  decl = (SAFETY_DIR / "declarations.h").read_text()
  safety_id = re.search(r"#define (SAFETY_\w+) " + str(safety_model) + r"U\b", decl).group(1)
  hooks = re.search(r"\{" + safety_id + r", &(\w+)\}", (SAFETY_DIR / "safety.h").read_text()).group(1)
  header = next(p for p in MODES_DIR.glob("*.h") if re.search(r"safety_hooks " + hooks + r" =", _code(p)))
  texts, todo = [], [header]
  while todo:
    text = _code(todo.pop())
    texts.append(text)
    todo += [MODES_DIR / inc for inc in re.findall(r'#include "opendbc/safety/modes/(\w+\.h)"', text)]
  return texts


def _writes(texts: list[str], field: str) -> bool:
  # a write counts in the mode's own header, or in an included helper that header calls
  pattern = r"safety\." + field + r"\s*="
  bodies = {}
  for text in texts[1:]:
    for m in re.finditer(r"\b(\w+)\([^;{)]*\)\s*\{", text):
      depth, i = 1, m.end()
      while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
      bodies[m.group(1)] = text[m.end():i]
  writers = {name for name, body in bodies.items() if re.search(pattern, body)}
  while new := {n for n, b in bodies.items() if n not in writers and any(re.search(r"\b" + w + r"\(", b) for w in writers)}:
    writers |= new
  return bool(re.search(pattern, texts[0])) or any(re.search(r"\b" + w + r"\(", texts[0]) for w in writers)


def _platforms():
  for fp in sorted(PLATFORMS):
    CP = interfaces[fp].get_non_essential_params(fp)
    if len(CP.safetyConfigs):
      yield fp, CP


@pytest.mark.parametrize("fp, CP", list(_platforms()), ids=lambda x: x if isinstance(x, str) else "")
def test_main_and_button_match_panda(fp, CP):
  texts = _hooks_header(CP.safetyConfigs[-1].safetyModel.raw)
  sets_main = _writes(texts, "acc_main_on")
  assert mads_main_reported(CP.brand, CP.flags, fp) == sets_main
  # Hyundai and Tesla buttons depend on car and openpilot flags, covered in test_mads_brand_rules.py
  if CP.brand not in ("hyundai", "tesla"):
    sets_button = _writes(texts, "mads_button_press")
    assert mads_has_button(CP.brand, CP.flags, 0, 0, fp) == sets_button


def test_comments_are_not_writers(tmp_path):
  h = tmp_path / "x.h"
  h.write_text("// safety.acc_main_on = true;\n/* safety.mads_button_press =\n 1; */\nint x = 1;\n")
  assert "acc_main_on" not in _code(h) and "mads_button_press" not in _code(h)
