"""Live trip page: the page left of the camera, one swipe right from the road view.

Four big stats, where the drive is going, and a bar from the start to the destination colored by how the
drive went (comma's engagement states). The numbers come from tripstats.live (distance, engaged distance, time)
and navInstruction (distance remaining); the bar is a distance log kept here (tripstats.progress).
"""
from __future__ import annotations

import datetime
import time

import raylib_nb as rl

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import progress as pr
from openpilot.selfdrive.ui.mici.onroad.driver_state import DriverStateRenderer
from openpilot.selfdrive.ui.mici.onroad.navigation import _nav_theme_rgb
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FONT_SCALE, FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

BG = rl.Color(9, 14, 19, 255)
MUTED = rl.Color(162, 175, 185, 255)
LIGHT = rl.Color(205, 213, 220, 255)
WHITE = rl.WHITE
OTHER_RGB = {pr.OVERRIDE: (150, 160, 154), pr.LAT_ONLY: (40, 130, 215), pr.DISENGAGED: (72, 79, 86)}  # connect's engagedGrey, MADS blue, off
BAR_X, BAR_Y, BAR_H, BAR_PAD = 20, 160, 28, 20
ASCENT = 0.80   # Inter baseline, as a fraction of the font px
DEST_REFRESH_S = 2.0


def _color(rgb, a: float = 1.0) -> rl.Color:
  return rl.Color(rgb[0], rgb[1], rgb[2], int(255 * a))


class TripProgressPage(Widget):
  def __init__(self):
    super().__init__()
    self._log = pr.SegmentLog()
    self._start = -1.0
    self._last_m = 0.0
    self._state = pr.DISENGAGED
    self._dest = pr.UNKNOWN_DESTINATION
    self._dest_t = 0.0
    self._dm = DriverStateRenderer(background=False)

  def record(self) -> None:
    """Every UI frame, also while this page is off screen: add the distance since last frame to the bar log."""
    live = ts.live
    if not live.active:
      return
    if live.start_wall != self._start or live.m < self._last_m:
      self._log, self._start, self._last_m = pr.SegmentLog(), live.start_wall, 0.0
    sm = ui_state.sm
    ss = sm['selfdriveState']
    self._state = pr.classify(bool(ss.enabled), str(ss.state), bool(sm['carControl'].latActive))
    self._log.add(live.m - self._last_m, self._state)
    self._last_m = live.m

  def _destination(self) -> str:
    now = time.monotonic()
    if now - self._dest_t > DEST_REFRESH_S:
      self._dest_t = now
      try:
        self._dest = pr.destination_name(ui_state.params.get("NavDestination"))
      except Exception:
        self._dest = pr.UNKNOWN_DESTINATION
    return self._dest

  @staticmethod
  def _text(text: str, x: float, baseline: float, px: float, weight: FontWeight, color: rl.Color, right: bool = False) -> float:
    font = gui_app.font(weight)
    size = px / FONT_SCALE
    w = measure_text_cached(font, text, size).x
    rl.draw_text_ex(font, text, rl.Vector2(x - w if right else x, baseline - ASCENT * px), size, 0, color)
    return w

  def _width(self, text: str, px: float, weight: FontWeight) -> float:
    return measure_text_cached(gui_app.font(weight), text, px / FONT_SCALE).x

  def _render(self, rect: rl.Rectangle) -> None:
    x0, y0 = rect.x, rect.y
    rl.draw_rectangle_rec(rect, BG)
    rl.draw_circle_gradient(rl.Vector2(x0, y0), 260, rl.Color(3, 5, 7, 150), rl.BLANK)

    live = ts.live
    sm = ui_state.sm
    nav = sm['navInstruction']
    routing = sm.valid['navInstruction'] and sm.alive['navInstruction']
    remaining = max(0.0, nav.distanceRemaining) if routing else None
    nums = pr.trip_numbers(live.m, live.e, live.dur, remaining, bool(ui_state.is_metric))

    # DM icon, the same corner as the AR view
    self._dm.set_should_draw(True)
    self._dm.set_dimmed(1.0 if not ui_state.started else 0.0 if ui_state.always_on_dm else float(self._state == pr.DISENGAGED))
    self._dm.set_show_under_alerts(True)
    self._dm.set_position(x0 + 4, y0 + 4)
    self._dm.render()

    # Driving to <destination>
    bold, med = FontWeight.BOLD, FontWeight.MEDIUM
    w = self._text('Driving to', x0 + 68, y0 + 40, 28, med, MUTED)
    self._text(self._destination(), x0 + 68 + w + 10, y0 + 40, 36, bold, WHITE)

    # four big stats, spread by their own widths
    cols = [('remaining', nums['remaining']), ('traveled', nums['traveled']), ('time', nums['time']), ('engaged', nums['engaged'])]
    widths = [max(self._width(v, 50, bold) + (4 + self._width(u, 22, bold) if u else 0), self._width(lbl, 22, med)) for lbl, (v, u) in cols]
    gap = (rect.width - 28 - sum(widths)) / 3
    x = x0 + 14
    for (lbl, (v, u)), cw in zip(cols, widths, strict=True):
      vw = self._text(v, x, y0 + 102, 50, bold, WHITE)
      if u:
        self._text(u, x + vw + 4, y0 + 102, 22, bold, LIGHT)
      self._text(lbl, x + 1, y0 + 126, 22, med, MUTED)
      x += cw + gap

    self._draw_bar(rect, nums['frac'], live.active)
    self._draw_legend(x0, y0)

    # arrive time in the corner, on a vignette, as in the AR view
    rl.draw_circle_gradient(rl.Vector2(x0 + rect.width, y0 + rect.height), 230, rl.Color(3, 5, 7, 215), rl.BLANK)
    if routing:
      arrive = datetime.datetime.now() + datetime.timedelta(seconds=max(0.0, nav.timeRemaining))
      self._text(f'{(arrive.hour - 1) % 12 + 1}:{arrive.minute:02d}', x0 + rect.width - 14, y0 + rect.height - 2, 44, bold, WHITE, right=True)
      self._text('arrive', x0 + rect.width - 14, y0 + rect.height - 36, 26, bold, rl.Color(225, 231, 238, 255), right=True)

  def _rgb(self, state: int):
    return _nav_theme_rgb() if state == pr.ENGAGED else OTHER_RGB[state]

  def _draw_bar(self, rect: rl.Rectangle, frac: float | None, active: bool) -> None:
    x0 = rect.x + BAR_X
    x1 = rect.x + rect.width - BAR_PAD
    y, h = rect.y + BAR_Y, BAR_H
    cy = y + h / 2
    w = x1 - x0
    done = 0.0 if frac is None else frac
    xc = x0 + w * done
    # what is left of the trip: dots
    d = x1 - xc
    n = int(d // 16)
    for i in range(n):
      rl.draw_circle_v(rl.Vector2(xc + 22 + i * 16, cy), 4, rl.Color(255, 255, 255, 70))
    # traveled: caps in the first and last run's color, runs square between the cap centers
    spans = self._log.spans(max(self._log.total, 1.0) / max(done, 1e-3)) if self._log.runs and frac else []
    if spans and xc - x0 > h:
      r = h / 2
      rl.draw_circle_v(rl.Vector2(x0 + r, cy), r, _color(self._rgb(spans[0][2])))
      rl.draw_circle_v(rl.Vector2(xc - r, cy), r, _color(self._rgb(spans[-1][2])))
      lo, hi = x0 + r, xc - r
      for a, b, st in spans:
        sx0, sx1 = max(lo, x0 + w * a), min(hi, x0 + w * b)
        if sx1 > sx0:
          rl.draw_rectangle_rec(rl.Rectangle(round(sx0), y, max(1.0, round(sx1) - round(sx0)), h), _color(self._rgb(st)))
    # destination ring, and the car: white ring over the current state's color
    rl.draw_circle_v(rl.Vector2(x1, cy), 9, BG)
    rl.draw_ring(rl.Vector2(x1, cy), 6, 9, 0, 360, 24, WHITE)
    if frac is not None and active:
      rl.draw_circle_v(rl.Vector2(xc, cy + 3), 19, rl.Color(0, 0, 0, 110))
      rl.draw_circle_v(rl.Vector2(xc, cy), 17, WHITE)
      rl.draw_circle_v(rl.Vector2(xc, cy), 11, _color(self._rgb(self._state)))
      label = f'{round(done * 100)}%'
      self._text(label, min(max(xc, rect.x + 36), x1 - 28) - self._width(label, 26, FontWeight.BOLD) / 2, y - 12, 26, FontWeight.BOLD, WHITE)

  def _draw_legend(self, x0: float, y0: float) -> None:
    present = {st for _, st in self._log.runs} | {self._state}
    x = x0 + 20
    items = [st for st in (pr.ENGAGED, pr.OVERRIDE, pr.LAT_ONLY, pr.DISENGAGED) if st in present]
    total = sum(26 + self._width(pr.NAMES[st], 20, FontWeight.MEDIUM) + 16 for st in items)
    if total > 370:   # leave the arrive time its corner
      return
    for st in items:
      rl.draw_circle_v(rl.Vector2(x + 6.5, y0 + 215.5), 6.5, _color(self._rgb(st)))
      x += 20 + self._text(pr.NAMES[st], x + 20, y0 + 224, 20, FontWeight.MEDIUM, LIGHT) + 16
