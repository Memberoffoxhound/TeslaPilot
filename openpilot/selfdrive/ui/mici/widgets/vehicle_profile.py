"""Per-make Home long-mode badge: stock logo and OEM cruise name.

No openpilot imports at the top level, so it unit-tests without a build.
"""
from __future__ import annotations

from typing import NamedTuple


class Make(NamedTuple):
  # stock badge: logo path (None = text_rows icon), draw size, OEM cruise letters,
  # optional two-line text icon, OEM letter size, letter-column width
  logo: str | None
  logo_wh: tuple[int, int]
  stock_label: str
  text_rows: tuple[str, str] | None = None
  letter_sz: int = 11
  col_w: int = 16  # Kia SCC needs a wider column so the C edge is not a hard line


# OEM cruise names stay on the make so a new car adds its own term here.
MAKES: dict[str, Make] = {
  "tesla": Make("icons_mici/tesla_t.png", (48, 48), "TACC"),
  "kia": Make("icons_mici/kia.png", (120, 48), "SCC", letter_sz=22, col_w=22),
  # default: 50px text icon (STOCK / ACC), no car.png
  "generic": Make(None, (50, 48), "ACC", ("STOCK", "ACC")),
}


def make(CP) -> str:
  """tesla | kia | generic from CarParams (or None)."""
  if CP is None:
    return "generic"
  if CP.brand == "tesla":
    return "tesla"
  # HKG shares brand "hyundai"; Kia platforms are KIA_*
  if CP.brand == "hyundai" and CP.carFingerprint.startswith("KIA_"):
    return "kia"
  return "generic"
