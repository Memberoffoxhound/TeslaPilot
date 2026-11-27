# Live trip page, one swipe right of the camera: driving-to and stats, plus the trip bar.
from __future__ import annotations

import datetime
import time

import raylib_nb as rl

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import progress as pr
from openpilot.selfdrive.ui.mici.onroad.driver_state import DriverStateRenderer
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FONT_SCALE, FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

BG = rl.Color(9, 14, 19, 255)
MUTED = rl.Color(162, 175, 185, 255)
LIGHT = rl.Color(205, 213, 220, 255)
WHITE = rl.WHITE
ARRIVE = rl.Color(225, 231, 238, 255)
BAR_X, BAR_Y, BAR_H, BAR_PAD = 20, 148, 26, 20
TRACK = rl.Color(255, 255, 255, int(255 * pr.TRACK_ALPHA))
ASCENT = 0.80   # Inter baseline, as a fraction of the font px
ARRIVE_RESERVE = 130  # the arrive time sits in the lower right; the legend must stop short of it


def _color(rgb, a: float = 1.0) -> rl.Color:
  return rl.Color(rgb[0], rgb[1], rgb[2], int(255 * a))


def _fade(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(c.a * a))


class TripProgressPage(Widget):
  def __init__(self):
    super().__init__()
    self._log = pr.SegmentLog()
    self._start = -1.0
    self._last_m = 0.0
    self._state = pr.DISENGAGED
    self._phase_t0 = time.monotonic()
    self._was_on = False
    self._dm = DriverStateRenderer(background=False)

  def record(self) -> None:
    # every UI frame, also while this page is off screen: add the distance since last frame to the bar log
    live = ts.live
    if not live.active:
      return
    if live.start_wall != self._start or live.m < self._last_m:
      self._log, self._start, self._last_m = pr.SegmentLog(), live.start_wall, 0.0
    sm = ui_state.sm
    ss = sm['selfdriveState']
    # mads is optional: LAT_ONLY coloring only when the fork exposes selfdriveStateSP
    mads = 'selfdriveStateSP' in sm.data
    self._state = pr.classify(bool(ss.enabled), str(ss.state), bool(sm['carControl'].latActive), mads=mads)
    self._log.add(live.m - self._last_m, self._state)
    self._last_m = live.m

  def _destination(self) -> str:
    return pr.destination_name(ui_state.nav_destination).lower()

  def _update_state(self):
    # start on 'driving to' each time the page is swiped into view
    on = abs(self.rect.x) < 8
    if on and not self._was_on:
      self._phase_t0 = time.monotonic()
    self._was_on = on

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
    a_dest, a_stats = pr.fade_alphas(time.monotonic() - self._phase_t0)

    # DM icon, the same corner as the AR view, always on
    self._dm.set_should_draw(True)
    always_on = bool(getattr(ui_state, 'always_on_dm', False))
    self._dm.set_dimmed(1.0 if not ui_state.started else 0.0 if always_on else float(self._state == pr.DISENGAGED))
    self._dm.set_show_under_alerts(True)
    dm_size = self._dm.rect.width
    self._dm.set_position(x0 + rect.width - 4 - dm_size, y0 + 4)
    self._dm.render()

    bold, med = FontWeight.BOLD, FontWeight.MEDIUM
    if a_dest > 0.02:
      self._draw_dest(x0, y0, a_dest, bold, med)
    if a_stats > 0.02:
      self._draw_stats(x0, y0, rect.width, nums, a_stats, bold, med)

    self._draw_bar(rect, nums['frac'], live.active)
    self._draw_legend(x0, y0, rect.width)

    # arrive time below the bar, in the lower right corner, on a vignette
    rl.draw_circle_gradient(rl.Vector2(x0 + rect.width, y0 + rect.height), 200, rl.Color(3, 5, 7, 215), rl.BLANK)
    if routing:
      arrive = datetime.datetime.now() + datetime.timedelta(seconds=max(0.0, nav.timeRemaining))
      self._text(f'{(arrive.hour - 1) % 12 + 1}:{arrive.minute:02d}', x0 + rect.width - 14, y0 + rect.height - 4, 36, bold, WHITE, right=True)
      self._text('arrive', x0 + rect.width - 14, y0 + rect.height - 44, 20, bold, ARRIVE, right=True)

  def _draw_dest(self, x0: float, y0: float, a: float, bold, med) -> None:
    self._text('driving to', x0 + 16, y0 + 42, 32, med, _fade(MUTED, a))
    dest, size, room = self._destination(), 80, self._rect.width - 16 - 4 - self._dm.rect.width - 8
    while size > 48 and self._width(dest, size, bold) > room:
      size -= 2
    self._text(dest, x0 + 16, y0 + 114, size, bold, _fade(WHITE, a))

  def _draw_stats(self, x0: float, y0: float, width: float, nums: dict, a: float, bold, med) -> None:
    cols = [(abbr, nums[key]) for abbr, key in (('rem', 'remaining'), ('trav', 'traveled'), ('time', 'time'), ('eng', 'engaged'))]
    vs, us, ls, min_gap = 56, 22, 20, 12.0
    right = width - 4 - self._dm.rect.width - 16
    while vs >= 40:
      widths = [max(self._width(v, vs, bold) + (4 + self._width(u, us, bold) if u else 0), self._width(lbl, ls, med)) for lbl, (v, u) in cols]
      if sum(widths) + min_gap * 3 <= right - 16:
        break
      vs -= 2
      us = max(16, us - 1)
    gap = max(min_gap, (right - 16 - sum(widths)) / 3)
    x = x0 + 16
    for (lbl, (v, u)), cw in zip(cols, widths, strict=True):
      vw = self._text(v, x, y0 + 70, vs, bold, _fade(WHITE, a))
      if u:
        self._text(u, x + vw + 4, y0 + 70, us, bold, _fade(LIGHT, a))
      self._text(lbl, x, y0 + 94, ls, med, _fade(MUTED, a))
      x += cw + gap

  def _draw_bar(self, rect: rl.Rectangle, frac: float | None, active: bool) -> None:
    x0 = rect.x + BAR_X
    x1 = rect.x + rect.width - BAR_PAD
    y, h = rect.y + BAR_Y, BAR_H
    cy = y + h / 2
    w = x1 - x0
    done = 0.0 if frac is None else frac
    xc = x0 + w * done
    rl.draw_rectangle_rounded(rl.Rectangle(x0, y, w, h), 1.0, 8, TRACK)
    spans = self._log.spans(max(self._log.total, 1.0) / max(done, 1e-3)) if self._log.runs and frac else []
    if spans and xc - x0 > h:
      r = h / 2
      rl.draw_circle_v(rl.Vector2(x0 + r, cy), r, _color(pr.BAR_RGB[spans[0][2]]))
      rl.draw_circle_v(rl.Vector2(xc - r, cy), r, _color(pr.BAR_RGB[spans[-1][2]]))
      lo, hi = x0 + r, xc - r
      for a, b, st in spans:
        sx0, sx1 = max(lo, x0 + w * a), min(hi, x0 + w * b)
        if sx1 > sx0:
          rl.draw_rectangle_rec(rl.Rectangle(round(sx0), y, max(1.0, round(sx1) - round(sx0)), h), _color(pr.BAR_RGB[st]))
    rl.draw_circle_v(rl.Vector2(x1, cy), 9, BG)
    rl.draw_ring(rl.Vector2(x1, cy), 6, 9, 0, 360, 24, WHITE)
    if frac is not None and active:
      rl.draw_circle_v(rl.Vector2(xc, cy + 3), 19, rl.Color(0, 0, 0, 110))
      rl.draw_circle_v(rl.Vector2(xc, cy), 17, WHITE)
      rl.draw_circle_v(rl.Vector2(xc, cy), 11, _color(pr.BAR_RGB[self._state]))
      # percent sits just above the bar, and shifts left if it would hit the destination ring
      label = f'{round(done * 100)}%'
      self._text(label, min(max(xc, rect.x + 36), x1 - 36) - self._width(label, 22, FontWeight.BOLD) / 2, y - 8, 22, FontWeight.BOLD, WHITE)

  def _draw_legend(self, x0: float, y0: float, width: float) -> None:
    present = {st for _, st in self._log.runs} | {self._state}
    items = [st for st in (pr.ENGAGED, pr.OVERRIDE, pr.LAT_ONLY, pr.DISENGAGED) if st in present]
    # drop items from the right until the row clears the arrive time
    while items and sum(26 + self._width(pr.NAMES[st], 18, FontWeight.MEDIUM) + 14 for st in items) > width - 16 - ARRIVE_RESERVE:
      items.pop()
    x, y = x0 + 16, y0 + 214
    for st in items:
      rl.draw_circle_v(rl.Vector2(x + 6, y + 1), 6, _color(pr.BAR_RGB[st]))
      x += 18 + self._text(pr.NAMES[st], x + 18, y + 8, 18, FontWeight.MEDIUM, LIGHT) + 14
