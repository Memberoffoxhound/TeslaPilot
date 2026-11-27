"""Trip progress for the live trip page: what the drive so far looked like, by distance, and its numbers.

Pure: no openpilot imports beyond the card helpers. Constant memory: runs of equal state merge when too many.
"""
from __future__ import annotations

import math

from openpilot.selfdrive.ui.tripstats.card import fmt_dist
from openpilot.selfdrive.ui.tripstats.recorder import COLORS, MANUAL, ENGAGED as REC_ENGAGED, OVERRIDE as REC_OVERRIDE
from openpilot.selfdrive.ui.tripstats.store import engaged_pct

DISENGAGED, ENGAGED, OVERRIDE, LAT_ONLY = range(4)
NAMES = ("disengaged", "engaged", "override", "lateral only")
MAX_RUNS = 240
UNKNOWN_DESTINATION = "your destination"
HOLD_S, FADE_S = 4.5, 0.4  # each top-half state holds this long, then a short crossfade
PEEK_PX, PEEK_S, PEEK_OUT_S = 36.0, 0.6, 0.18  # drive-start bounce: camera shifts this many px, then springs back
TRACK_ALPHA = 0.15  # torque bar track at rest, used for unrealized trip progress
# engagement metric colors: connect / tripstats timeline. lateral-only is not a connect state.
LAT_ONLY_RGB = (0x2A, 0x7A, 0xB8)
BAR_RGB = {
  DISENGAGED: COLORS[MANUAL],     # drivingBlue
  ENGAGED: COLORS[REC_ENGAGED],   # engagedGreen
  OVERRIDE: COLORS[REC_OVERRIDE], # engagedGrey
  LAT_ONLY: LAT_ONLY_RGB,
}
_OVERRIDE_STATES = ("preEnabled", "overriding")   # the recorder's override layer (connect's engagedGrey)


def classify(enabled: bool, state: str, lat_active: bool) -> int:
  """selfdriveState and carControl to the bar's state. enabled counts as engaged, as in the trip recorder."""
  if enabled:
    return OVERRIDE if state in _OVERRIDE_STATES else ENGAGED
  return LAT_ONLY if lat_active else DISENGAGED     # MADS steering with no cruise


class SegmentLog:
  """[length m, state] runs along the trip."""

  def __init__(self) -> None:
    self.runs: list[list[float]] = []
    self.total = 0.0

  def add(self, meters: float, state: int) -> None:
    if meters <= 0:
      return
    self.total += meters
    if self.runs and self.runs[-1][1] == state:
      self.runs[-1][0] += meters
      return
    self.runs.append([meters, state])
    if len(self.runs) > MAX_RUNS:
      self._squash()

  def _squash(self) -> None:
    # the shortest run inside the trip joins its longer neighbor, so detail goes before the big picture
    i = min(range(1, len(self.runs) - 1), key=lambda k: self.runs[k][0])
    left, right = self.runs[i - 1], self.runs[i + 1]
    keep = left if left[0] >= right[0] else right
    keep[0] += self.runs[i][0]
    del self.runs[i]
    if i < len(self.runs) and self.runs[i - 1][1] == self.runs[i][1]:   # neighbors now alike: merge
      self.runs[i - 1][0] += self.runs[i][0]
      del self.runs[i]

  def spans(self, total_m: float) -> list[tuple[float, float, int]]:
    """(start, end, state) as fractions of the whole trip, total_m = traveled + remaining."""
    out, x = [], 0.0
    for length, state in self.runs:
      out.append((x / total_m, (x + length) / total_m, int(state)))
      x += length
    return out


def fmt_time(seconds: float) -> tuple[str, str]:
  s = max(0, int(seconds))
  return (f"{s // 3600}:{s % 3600 // 60:02d}", "h") if s >= 3600 else (f"{s // 60}:{s % 60:02d}", "min")


def trip_numbers(traveled_m: float, engaged_m: float, dur_s: float, remaining_m: float | None, metric: bool) -> dict:
  """The four big stats as (value, unit), and where the car is on the bar (0 to 1; None without a route)."""
  rem = ("--", "") if remaining_m is None else fmt_dist(max(0.0, remaining_m), metric)
  total = None if remaining_m is None else traveled_m + max(0.0, remaining_m)
  return {
    "remaining": rem,
    "traveled": fmt_dist(traveled_m, metric),
    "time": fmt_time(dur_s),
    "engaged": (str(engaged_pct(engaged_m, traveled_m)), "%"),
    "frac": None if not total else min(1.0, traveled_m / total),
  }


def destination_name(destination: dict | None) -> str:
  """The NavDestination param's place_name, else a plain fallback."""
  name = str((destination or {}).get("place_name") or "").strip()
  return name or UNKNOWN_DESTINATION


def fade_alphas(t: float) -> tuple[float, float]:
  """(destination, stats) alphas. Each state holds HOLD_S seconds; the last FADE_S is a smooth crossfade."""
  span = 2 * HOLD_S
  x = t % span
  if x < HOLD_S - FADE_S:
    return 1.0, 0.0
  if x < HOLD_S:
    a = (x - (HOLD_S - FADE_S)) / FADE_S
    a = a * a * (3 - 2 * a)
    return 1.0 - a, a
  if x < span - FADE_S:
    return 0.0, 1.0
  a = (x - (span - FADE_S)) / FADE_S
  a = a * a * (3 - 2 * a)
  return a, 1.0 - a


def peek_offset(t: float, px: float = PEEK_PX, dur: float = PEEK_S, t_out: float = PEEK_OUT_S) -> float:
  """Pixels the camera shifts right, revealing the trip page on the left. Ease-out, then a spring back, done at dur."""
  if t <= 0 or t >= dur:
    return 0.0
  if t < t_out:
    u = t / t_out
    return px * (1.0 - (1.0 - u) ** 3)
  u = (t - t_out) / (dur - t_out)
  return px * math.exp(-5.0 * u) * math.cos(3.2 * math.pi * u)
