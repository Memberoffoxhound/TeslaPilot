from __future__ import annotations

import os

import raylib_nb as rl
from openpilot.selfdrive.ui.mici.widgets.trip_row import GREY, WHITE
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.dpbridge.kernel_ok import bt_kernel
from openpilot.system.dpbridge.nowplaying import fmt_mmss, read_state, send_command, visible
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

BG = rl.Color(20, 20, 20, 220)
TRACK = rl.Color(60, 60, 60, 255)
PLACEHOLDER = rl.Color(40, 40, 40, 255)
NOTE = rl.Color(180, 180, 180, 255)
BTN_BG = rl.Color(40, 40, 40, 255)
ERROR = rl.Color(230, 200, 180, 255)


def _tri(*pts: tuple[float, float]):
  # raylib_nb has no draw_triangle: fill row by row
  edges = [(pts[i], pts[(i + 1) % 3]) for i in range(3)]
  for y in range(int(min(p[1] for p in pts)), int(max(p[1] for p in pts)) + 1):
    xs = [a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]) for a, b in edges if a[1] != b[1] and min(a[1], b[1]) <= y <= max(a[1], b[1])]
    if xs:
      rl.draw_line(int(min(xs)), y, int(max(xs)) + 1, y, WHITE)


def _ellipsize(font, text: str, size: int, width: float) -> str:
  if not text or measure_text_cached(font, text, size).x <= width:
    return text
  ell = "..."
  if measure_text_cached(font, ell, size).x > width:
    return ""
  lo, hi, best = 0, len(text), ""
  while lo <= hi:
    mid = (lo + hi) // 2
    cand = text[:mid] + ell
    if measure_text_cached(font, cand, size).x <= width:
      best, lo = cand, mid + 1
    else:
      hi = mid - 1
  return best


class NowPlayingCard(Widget):
  # fills the mici home area above the footer (536x240, 48 px footer, 4 px pads: 184 px)
  H = 184
  ART = 96
  BTN = 72  # well above the 48 px footer icons, comfortable while driving
  TITLE = 28
  ARTIST = 20
  ALBUM = 18
  TIME = 16
  BAR = 6
  STATUS = 18

  def __init__(self):
    super().__init__()
    self._state: dict = {}
    self._tex: rl.Texture | None = None
    self._art_key: str | None = None
    self._bold = gui_app.font(FontWeight.BOLD)
    self._roman = gui_app.font(FontWeight.ROMAN)
    self._btns: dict[str, rl.Rectangle] = {}
    self.set_visible(False)

  def _unload_art(self):
    if self._tex is not None:
      rl.unload_texture(self._tex)
      self._tex = None
    self._art_key = None

  def _reload_art(self, path: str | None):
    if path == self._art_key:
      return
    self._unload_art()
    if not path or not os.path.isfile(path):
      return
    try:
      image = rl.load_image(path)
      self._tex = rl.load_texture_from_image(image)
      rl.unload_image(image)
      self._art_key = path
    except Exception:
      self._unload_art()

  def _update_state(self):
    self._state = read_state() if bt_kernel() else {}  # no card off the dpbridge kernel
    show = visible(self._state)
    self.set_visible(show)
    if show:
      art = self._state.get("art")
      self._reload_art(art if isinstance(art, str) else None)
    elif self._tex is not None:
      self._unload_art()

  def _draw_placeholder(self, x: float, y: float, size: float):
    r = rl.Rectangle(x, y, size, size)
    rl.draw_rectangle_rounded(r, 0.12, 6, PLACEHOLDER)
    s = size / 56.0
    cx, cy = x + size * 0.52, y + size * 0.58
    rl.draw_circle(int(cx - 7 * s), int(cy), max(4, int(6 * s)), NOTE)
    rl.draw_circle(int(cx + 6 * s), int(cy - 4 * s), max(4, int(6 * s)), NOTE)
    rl.draw_rectangle(int(cx - 2 * s), int(cy - 22 * s), max(3, int(3 * s)), max(12, int(22 * s)), NOTE)
    rl.draw_rectangle(int(cx + 11 * s), int(cy - 26 * s), max(3, int(3 * s)), max(12, int(22 * s)), NOTE)
    rl.draw_rectangle(int(cx - 2 * s), int(cy - 26 * s), max(10, int(16 * s)), max(3, int(4 * s)), NOTE)

  def _btn_rect(self, i: int, rect: rl.Rectangle, btn: int) -> rl.Rectangle:
    y = rect.y + rect.height - 6 - btn
    x = rect.x + 8 + i * (btn + 10)
    return rl.Rectangle(x, y, btn, btn)

  def _draw_prev(self, r: rl.Rectangle):
    cy, mid, s = r.y + r.height / 2, r.x + r.width / 2, r.width / 48.0
    rl.draw_rectangle(int(mid - 12 * s), int(cy - 10 * s), max(3, int(4 * s)), max(16, int(20 * s)), WHITE)
    _tri((mid + 14 * s, cy - 12 * s), (mid + 14 * s, cy + 12 * s), (mid - 6 * s, cy))

  def _draw_next(self, r: rl.Rectangle):
    cy, mid, s = r.y + r.height / 2, r.x + r.width / 2, r.width / 48.0
    _tri((mid - 14 * s, cy - 12 * s), (mid - 14 * s, cy + 12 * s), (mid + 6 * s, cy))
    rl.draw_rectangle(int(mid + 10 * s), int(cy - 10 * s), max(3, int(4 * s)), max(16, int(20 * s)), WHITE)

  def _draw_play_pause(self, r: rl.Rectangle, playing: bool):
    cy, mid, s = r.y + r.height / 2, r.x + r.width / 2, r.width / 48.0
    if playing:
      rl.draw_rectangle(int(mid - 11 * s), int(cy - 13 * s), max(5, int(7 * s)), max(18, int(26 * s)), WHITE)
      rl.draw_rectangle(int(mid + 4 * s), int(cy - 13 * s), max(5, int(7 * s)), max(18, int(26 * s)), WHITE)
    else:
      _tri((mid - 10 * s, cy - 14 * s), (mid - 10 * s, cy + 14 * s), (mid + 16 * s, cy))

  def _handle_mouse_release(self, mouse_pos):
    if ui_state.engaged:
      return
    pt = rl.Vector2(mouse_pos.x, mouse_pos.y)
    playing = self._state.get("status") == "playing"
    for name, r in self._btns.items():
      if rl.check_collision_point_rec(pt, r):
        cmd = "pause" if name == "playpause" and playing else ("play" if name == "playpause" else name)
        send_command(cmd)
        return

  def _layout_sizes(self, rect: rl.Rectangle) -> tuple[int, int]:
    # keep the 72 px buttons; remaining height goes to the art
    pad, gap, btn = 6, 4, self.BTN
    art = max(72, min(self.ART, int(rect.height - pad - gap - btn - pad)))
    return art, btn

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.08, 8, BG)
    st = self._state
    art, btn = self._layout_sizes(rect)
    ax = rect.x + 8
    top = rect.y + 6
    if self._tex is not None:
      src = rl.Rectangle(0, 0, self._tex.width, self._tex.height)
      dest = rl.Rectangle(ax, top, art, art)
      rl.draw_texture_pro(self._tex, src, dest, rl.Vector2(0, 0), 0, rl.WHITE)
    else:
      self._draw_placeholder(ax, top, art)

    tx = ax + art + 12
    tw = rect.x + rect.width - 10 - tx
    title_sz, artist_sz, album_sz, time_sz = self.TITLE, self.ARTIST, self.ALBUM, self.TIME
    y = top + 2
    title = _ellipsize(self._bold, st.get("title") or "", title_sz, tw)
    rl.draw_text_ex(self._bold, title, rl.Vector2(tx, y), title_sz, 0, WHITE)
    y += title_sz + 2

    artist = _ellipsize(self._roman, st.get("artist") or "", artist_sz, tw)
    if artist:
      rl.draw_text_ex(self._roman, artist, rl.Vector2(tx, y), artist_sz, 0, GREY)
      y += artist_sz + 2
    album = _ellipsize(self._roman, st.get("album") or "", album_sz, tw)
    if album:
      rl.draw_text_ex(self._roman, album, rl.Vector2(tx, y), album_sz, 0, GREY)

    pos = fmt_mmss(st.get("position_ms"))
    dur = fmt_mmss(st.get("duration_ms"))
    pf, df = measure_text_cached(self._roman, pos, time_sz), measure_text_cached(self._roman, dur, time_sz)
    by = top + art - time_sz
    rl.draw_text_ex(self._roman, pos, rl.Vector2(tx, by - 2), time_sz, 0, GREY)
    rl.draw_text_ex(self._roman, dur, rl.Vector2(tx + tw - df.x, by - 2), time_sz, 0, GREY)
    bx0, bx1 = tx + pf.x + 8, tx + tw - df.x - 8
    if bx1 > bx0 + 4:
      rl.draw_rectangle_rounded(rl.Rectangle(bx0, by + 4, bx1 - bx0, self.BAR), 0.5, 4, TRACK)
      duration = st.get("duration_ms") or 0
      position = st.get("position_ms") or 0
      if duration > 0:
        frac = max(0.0, min(1.0, position / duration))
        fill = max(6.0, (bx1 - bx0) * frac)
        rl.draw_rectangle_rounded(rl.Rectangle(bx0, by + 4, fill, self.BAR), 0.5, 4, WHITE)

    names = ("previous", "playpause", "next")
    self._btns = {n: self._btn_rect(i, rect, btn) for i, n in enumerate(names)}
    playing = st.get("status") == "playing"
    for name, r in self._btns.items():
      rl.draw_rectangle_rounded(r, 0.16, 6, BTN_BG)
      if name == "previous":
        self._draw_prev(r)
      elif name == "next":
        self._draw_next(r)
      else:
        self._draw_play_pause(r, playing)

    status = (st.get("error") or st.get("stream") or "").strip()
    if status:
      sx = self._btns["next"].x + btn + 12
      sw = rect.x + rect.width - 10 - sx
      font_color = ERROR if st.get("error") else GREY
      line = _ellipsize(self._roman, status, self.STATUS, sw)
      sy = self._btns["next"].y + (btn - self.STATUS) / 2
      rl.draw_text_ex(self._roman, line, rl.Vector2(sx, sy), self.STATUS, 0, font_color)
