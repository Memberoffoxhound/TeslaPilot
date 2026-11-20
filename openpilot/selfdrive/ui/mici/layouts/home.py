from __future__ import annotations

import datetime
import functools
import math
import time

from openpilot.cereal import log
import raylib_nb as rl
from collections.abc import Callable
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.layouts import HBoxLayout
from openpilot.system.ui.widgets.icon_widget import IconWidget
from openpilot.selfdrive.ui.mici.widgets.fill_icon import FillIcon
from openpilot.system.ui.widgets.label import UnifiedLabel, gui_label
from importlib.resources import as_file
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_DIR, TextAlignment, TextAlignmentVertical
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.ui_state import ui_state, ChestnutState
from openpilot.selfdrive.ui import tripstats
from openpilot.selfdrive.ui.mici.widgets.trip_row import GREY, WHITE, draw_trip_row, fmt_trip
from openpilot.selfdrive.ui.mici.widgets.vehicle_profile import MAKES, make as car_make
from openpilot.common.version import RELEASE_BRANCHES

HOME_PADDING = 8
ALERTS_ZONE_WIDTH = 180
MICI_WORDMARK_SIZE = 80
SSA_ICON_SIZE = 48


def _wordmark_font() -> rl.Font:
  """TeslaPilot wordmark glyphs from TESLA.ttf (T-E-S-L-A-P-I-L-O-T). Falls back to Inter DISPLAY."""
  try:
    cps = sorted(map(ord, "TESLAPILOT"))
    with as_file(FONT_DIR) as fs:
      font = rl.load_font_ex((fs / "TESLA.ttf").as_posix(), 200, cps, len(cps))
    if font.glyphCount > 0:
      rl.gen_texture_mipmaps(font.texture)
      rl.set_texture_filter(font.texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
      return font
  except Exception:
    pass
  return gui_app.font(FontWeight.DISPLAY)


_LABEL_FONT: rl.Font | None = None


def _label_font() -> rl.Font:
  # mipmapped Inter Bold so small letters render cleanly
  global _LABEL_FONT
  if _LABEL_FONT is None:
    cps = list(range(32, 127))
    with as_file(FONT_DIR) as fs:
      font = rl.load_font_ex((fs / FontWeight.BOLD).as_posix(), 200, cps, len(cps))
    if font.glyphCount > 0:
      rl.gen_texture_mipmaps(font.texture)
      rl.set_texture_filter(font.texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
    _LABEL_FONT = font if font.glyphCount > 0 else gui_app.font(FontWeight.BOLD)
  return _LABEL_FONT


NetworkType = log.DeviceState.NetworkType

class AlertsPill(Widget):
  ICON_OFFSET = 12
  COUNT_OFFSET = 40

  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 104, 52))

    self._pill_bg_txt = gui_app.texture("icons_mici/alerts_pill.png", 104, 52)
    self._alert_count_callback: Callable[[], int] | None = None
    self._alert_icon_callback: Callable[[], rl.Texture | None] | None = None

  def set_alert_count_callback(self, callback: Callable[[], int] | None,
                               icon_callback: Callable[[], rl.Texture | None] | None = None):
    self._alert_count_callback = callback
    self._alert_icon_callback = icon_callback

  def _render(self, _):
    alert_count = self._alert_count_callback() if self._alert_count_callback else 0
    if alert_count > 0:
      pill_w, pill_h = self._pill_bg_txt.width, self._pill_bg_txt.height
      rl.draw_texture_ex(self._pill_bg_txt, rl.Vector2(self.rect.x, self.rect.y), 0.0, 1.0, rl.WHITE)

      warning_txt = self._alert_icon_callback() if self._alert_icon_callback else None
      if warning_txt is not None:
        scale = 36 / max(warning_txt.width, warning_txt.height)
        warn_x = self.rect.x + self.ICON_OFFSET
        warn_y = self.rect.y + (pill_h - warning_txt.height * scale) / 2
        rl.draw_texture_ex(warning_txt, rl.Vector2(warn_x, warn_y), 0.0, scale, rl.WHITE)

      count_rect = rl.Rectangle(self.rect.x + self.COUNT_OFFSET, self.rect.y, pill_w - self.COUNT_OFFSET, pill_h)
      gui_label(count_rect, str(alert_count), font_size=36,
                alignment=TextAlignment.CENTER,
                alignment_vertical=TextAlignmentVertical.MIDDLE)


class NetworkIcon(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 60, 47))  # max size of all icons
    self._net_type = NetworkType.none
    self._net_strength = 0

    self._wifi_slash_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_slash.png", 54, 47)
    self._wifi_none_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_none.png", 54, 40)
    self._wifi_low_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_low.png", 54, 40)
    self._wifi_medium_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_medium.png", 54, 40)
    self._wifi_full_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_full.png", 54, 40)

    self._cell_none_txt = gui_app.texture("icons_mici/settings/network/cell_strength_none.png", 60, 40)
    self._cell_low_txt = gui_app.texture("icons_mici/settings/network/cell_strength_low.png", 60, 40)
    self._cell_medium_txt = gui_app.texture("icons_mici/settings/network/cell_strength_medium.png", 60, 40)
    self._cell_high_txt = gui_app.texture("icons_mici/settings/network/cell_strength_high.png", 60, 40)
    self._cell_full_txt = gui_app.texture("icons_mici/settings/network/cell_strength_full.png", 60, 40)

  def _update_state(self):
    device_state = ui_state.sm['deviceState']
    self._net_type = device_state.networkType
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _render(self, _):
    if self._net_type == NetworkType.wifi:
      # There is no 1
      draw_net_txt = {0: self._wifi_none_txt,
                      2: self._wifi_low_txt,
                      3: self._wifi_medium_txt,
                      4: self._wifi_full_txt,
                      5: self._wifi_full_txt}.get(self._net_strength, self._wifi_low_txt)
    elif self._net_type in (NetworkType.cell2G, NetworkType.cell3G, NetworkType.cell4G, NetworkType.cell5G):
      draw_net_txt = {0: self._cell_none_txt,
                      2: self._cell_low_txt,
                      3: self._cell_medium_txt,
                      4: self._cell_high_txt,
                      5: self._cell_full_txt}.get(self._net_strength, self._cell_none_txt)
    else:
      draw_net_txt = self._wifi_slash_txt

    draw_x = self._rect.x + (self._rect.width - draw_net_txt.width) / 2
    draw_y = self._rect.y + (self._rect.height - draw_net_txt.height) / 2

    if draw_net_txt == self._wifi_slash_txt:
      # Offset by difference in height between slashless and slash icons to make center align match
      draw_y -= (self._wifi_slash_txt.height - self._wifi_none_txt.height) / 2

    rl.draw_texture_ex(draw_net_txt, rl.Vector2(draw_x, draw_y), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * 0.9)))


VLABEL_H = 48
VLABEL_SZ = 11
VLABEL_COL_W = 16
VLABEL_GAP = 2  # icon to label


@functools.lru_cache(maxsize=16)
def _column_offsets(widths: tuple[float, ...], col: int) -> tuple[int, ...]:
  # whole-pixel x per letter around a shared center, cached per font, size and letters
  best: tuple[tuple[float, float], list[int]] | None = None
  for k in range(-4, 5):
    c = col / 2 + k / 8
    xs = [round(c - w / 2) for w in widths]
    centers = [xo + w / 2 for xo, w in zip(xs, widths, strict=True)]
    key = (round(max(centers) - min(centers), 3), abs(sum(centers) / len(centers) - col / 2))
    if best is None or key < best[0]:
      best = (key, xs)
  assert best is not None
  return tuple(best[1])


def draw_vertical_label(font: rl.Font, letters: str, x: float, y: float, fsz: int = VLABEL_SZ, col: int = VLABEL_COL_W,
                        h: float = VLABEL_H, color: rl.Color = WHITE, center: bool = False) -> None:
  # shared by LONG, TITS and the OEM letters: even pitch, glyphs pinned to the slot top
  pitch = h / len(letters)
  sizes = [measure_text_cached(font, ch, fsz) for ch in letters]
  if center:
    for i, (ch, sz) in enumerate(zip(letters, sizes, strict=True)):
      rl.draw_text_ex(font, ch, rl.Vector2(x + (col - sz.x) / 2, y + i * pitch + (pitch - sz.y) / 2), fsz, 0, color)
    return
  # LONG/TITS: whole pixels on one center column
  for i, (ch, xo) in enumerate(zip(letters, _column_offsets(tuple(sz.x for sz in sizes), col), strict=True)):
    rl.draw_text_ex(font, ch, rl.Vector2(round(x) + xo, round(y + i * pitch)), fsz, 0, color)


class LongModeBadge(Widget):
  """Footer: stock OEM cruise badge, or comma + LONG when openpilot long is on."""

  H = VLABEL_H
  COL_W = VLABEL_COL_W
  OP_LOGO_W = 30

  def __init__(self):
    super().__init__()
    self._comma = gui_app.texture("icons_mici/settings/comma_icon.png", 27, 48)
    self._logos = {
      name: gui_app.texture(m.logo, m.logo_wh[0], m.logo_wh[1])
      for name, m in MAKES.items() if m.logo is not None
    }
    self._font = gui_app.font(FontWeight.BOLD)
    self._op = False
    self._make_name = "generic"
    self._make = MAKES["generic"]
    self._logo_w = float(self._make.logo_wh[0])
    self._sync_rect()
    self.set_enabled(False)

  def _sync_rect(self):
    # keep layout-placed x/y; width tracks logo (+ OEM letters, unless text-only generic)
    col = self.COL_W if self._op else self._make.col_w
    side = 0 if (not self._op and self._make.text_rows is not None) else (4 + col)
    self.set_rect(rl.Rectangle(self.rect.x, self.rect.y, float(self._logo_w + side), float(self.H)))

  def _update_state(self):
    self._op = bool(ui_state.has_longitudinal_control)
    self._make_name = car_make(ui_state.CP)
    self._make = MAKES[self._make_name]
    self._logo_w = float(self.OP_LOGO_W if self._op else self._make.logo_wh[0])
    self._sync_rect()

  def _draw_text_icon(self, rows: tuple[str, str], x: float, y: float, w: float) -> None:
    # STOCK / ACC: largest bold size in the 50px slot; STOCK targets ~48px wide, tight rows
    pad, gap = 1.0, 1.0
    fsz = 40
    while fsz > 8:
      sizes = [measure_text_cached(self._font, row, fsz) for row in rows]
      # measure is a hair wider than ink; allow ~1px so STOCK ink can hit ~48
      if max(s.x for s in sizes) <= w + 1 and sum(s.y for s in sizes) + gap <= self.H - 2 * pad:
        break
      fsz -= 1
    sizes = [measure_text_cached(self._font, row, fsz) for row in rows]
    block = sum(s.y for s in sizes) + gap
    cy = y + (self.H - block) / 2
    for row, sz in zip(rows, sizes, strict=True):
      rl.draw_text_ex(self._font, row, rl.Vector2(x + (w - sz.x) / 2, cy), fsz, 0, WHITE)
      cy += sz.y + gap

  def _render(self, _) -> None:
    x, y, m = self.rect.x, self.rect.y, self._make
    if not self._op and m.text_rows is not None:
      # generic: STOCK/ACC two-row text is the whole badge (same bold font as TACC/SCC)
      self._draw_text_icon(m.text_rows, x, y, self._logo_w)
      return
    tex = self._comma if self._op else self._logos[self._make_name]
    rl.draw_texture_ex(tex, rl.Vector2(x + (self._logo_w - tex.width) / 2, y + (self.H - tex.height) / 2), 0.0, 1.0, rl.WHITE)
    if self._op:
      draw_vertical_label(_label_font(), "LONG", x + self._logo_w + VLABEL_GAP, y)
    else:
      draw_vertical_label(self._font, m.stock_label, x + self._logo_w + VLABEL_GAP, y, m.letter_sz, m.col_w, center=True)


class TitsBadge(Widget):
  # footer: wheel + vertical TITS, styled like the LONG badge, while TITS is on

  H = VLABEL_H
  WHEEL = 40

  def __init__(self):
    super().__init__()
    self._wheel = gui_app.texture("icons_mici/wheel.png", self.WHEEL, self.WHEEL)
    self.set_rect(rl.Rectangle(0, 0, float(self.WHEEL + 4 + VLABEL_COL_W), float(self.H)))
    self.set_enabled(False)

  def _render(self, _) -> None:
    x, y = self.rect.x, self.rect.y
    rl.draw_texture_ex(self._wheel, rl.Vector2(x, y + (self.H - self._wheel.height) / 2), 0.0, 1.0, WHITE)
    draw_vertical_label(_label_font(), "TITS", x + self.WHEEL + VLABEL_GAP, y)


class MiciHomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self._on_settings_click: Callable | None = None
    self._on_alerts_click: Callable | None = None
    self._alert_count_callback: Callable[[], int] | None = None

    self._version_text = self._get_version_text()
    self._wordmark_font = _wordmark_font()

    self._long_badge = LongModeBadge()
    self._tits_badge = TitsBadge()
    self._usb_icon = IconWidget("icons_mici/usb.png", (62, 40))
    self._chestnut_icon = IconWidget("icons_mici/chestnut_green.png", (54, 40))
    self._chestnut_loading_icon = IconWidget("icons_mici/chestnut.png", (68, 40))
    self._chestnut_failed_icon = IconWidget("icons_mici/chestnut_orange.png", (68, 40))
    self._chestnut_fill_icon = FillIcon("icons_mici/chestnut.png", (54, 40))
    self._mic_icon = IconWidget("icons_mici/microphone.png", (32, 46))
    self._body_icon = IconWidget("icons_mici/body.png", (54, 37))
    # Set Speed Assist shortcut: shown only while the toggle is on with openpilot longitudinal,
    # just left of the chestnut (Jetlink GPU link) icons; the row closes up when either is hidden
    self._ssa_icon = IconWidget("icons_mici/set_speed_assist.png", (SSA_ICON_SIZE, SSA_ICON_SIZE))

    self._alerts_pill = AlertsPill()

    self._status_bar_layout = HBoxLayout([
      IconWidget("icons_mici/settings.png", (48, 48), opacity=0.9),
      NetworkIcon(),
      self._long_badge,
      self._tits_badge,
      self._usb_icon,
      self._ssa_icon,
      self._chestnut_icon,
      self._chestnut_loading_icon,
      self._chestnut_failed_icon,
      self._chestnut_fill_icon,
      self._body_icon,
      self._mic_icon,
    ], spacing=18)

    self._version_label = UnifiedLabel("", font_size=36, text_color=GREY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._date_label = UnifiedLabel("", font_size=36, text_color=GREY, font_weight=FontWeight.ROMAN, max_width=480, wrap_text=False)
    self._branch_label = UnifiedLabel("", font_size=36, text_color=GREY, font_weight=FontWeight.ROMAN, scroll=True)
    self._trip_at = 0.0
    self._day_txt = ("Day", "0mi 0%")
    self._week_txt = ("Week", "0mi 0%")
    self._trip_hit = rl.Rectangle(0, 0, 0, 0)
    self._on_stats_click: Callable | None = None
    self._ssa_on = False
    self._ssa_hit = rl.Rectangle(0, 0, 0, 0)
    self._on_ssa_click: Callable | None = None
    self._tits_on = False
    self._tits_hit = rl.Rectangle(0, 0, 0, 0)
    self._on_tits_click: Callable | None = None
    self._accel_hit = rl.Rectangle(0, 0, 0, 0)
    self._on_models_click: Callable | None = None

  def _update_state(self):
    self._refresh_trip()

  def _refresh_trip(self):
    now = time.monotonic()
    if now - self._trip_at < 1.0:
      return
    self._trip_at = now
    t = tripstats.view(ui_state.params)
    self._day_txt = ("Day", fmt_trip(t["today_m"], t["today_e"], ui_state.is_metric))
    self._week_txt = ("Week", fmt_trip(t["week_m"], t["week_e"], ui_state.is_metric))
    self._ssa_on = ui_state.params.get_bool("SetSpeedAssist")
    self._tits_on = ui_state.tits_enabled

  def set_callbacks(self, on_settings: Callable | None = None, on_alerts: Callable | None = None,
                    on_stats: Callable | None = None,
                    on_set_speed_assist: Callable | None = None,
                    on_tits: Callable | None = None,
                    on_models: Callable | None = None,
                    alert_count_callback: Callable[[], int] | None = None,
                    alert_icon_callback: Callable[[], rl.Texture | None] | None = None):
    self._on_settings_click = on_settings
    self._on_alerts_click = on_alerts
    self._on_stats_click = on_stats
    self._on_ssa_click = on_set_speed_assist
    self._on_tits_click = on_tits
    self._on_models_click = on_models
    self._alert_count_callback = alert_count_callback
    self._alerts_pill.set_alert_count_callback(alert_count_callback, alert_icon_callback)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if self._on_tits_click and self._tits_hit.width > 0 and rl.check_collision_point_rec(rl.Vector2(mouse_pos.x, mouse_pos.y), self._tits_hit):
      self._on_tits_click()
      return
    if self._on_ssa_click and self._ssa_hit.width > 0 and rl.check_collision_point_rec(rl.Vector2(mouse_pos.x, mouse_pos.y), self._ssa_hit):
      self._on_ssa_click()
      return
    if self._on_models_click and self._accel_hit.width > 0 and rl.check_collision_point_rec(rl.Vector2(mouse_pos.x, mouse_pos.y), self._accel_hit):
      self._on_models_click()
      return
    if (self._on_stats_click and self._trip_hit.width > 0 and
        rl.check_collision_point_rec(rl.Vector2(mouse_pos.x, mouse_pos.y), self._trip_hit)):
      self._on_stats_click()
      return
    relative_x = mouse_pos.x - self.rect.x
    has_alerts = self._alert_count_callback and self._alert_count_callback() > 0
    if has_alerts and relative_x > self.rect.width - ALERTS_ZONE_WIDTH:
      if self._on_alerts_click:
        self._on_alerts_click()
    elif self._on_settings_click:
      self._on_settings_click()

  def _get_version_text(self) -> tuple[str, str, str, str] | None:
    version = ui_state.params.get("Version")
    branch = ui_state.params.get("GitBranch")
    commit = ui_state.params.get("GitCommit")

    if not all((version, branch, commit)):
      return None

    commit_date_raw = ui_state.params.get("GitCommitDate")
    try:
      unix_ts = int(commit_date_raw.strip("'").split()[0])
      date_str = datetime.datetime.fromtimestamp(unix_ts).strftime("%b %d")
    except (ValueError, IndexError, TypeError, AttributeError):
      date_str = ""

    return version, branch, commit[:7], date_str

  def _render(self, _):
    text_pos = rl.Vector2(self.rect.x - 2 + HOME_PADDING, self.rect.y + 2)
    mark = "TESLAPILOT"
    avail = max(200, self.rect.width - HOME_PADDING * 2)
    wm = MICI_WORDMARK_SIZE
    while wm > 28 and measure_text_cached(self._wordmark_font, mark, wm).x > avail:
      wm -= 2
    rl.draw_text_ex(self._wordmark_font, mark, text_pos, wm, 0, WHITE)

    if self._version_text is not None:
      release_branch = self._version_text[1] in RELEASE_BRANCHES
      version_pos = rl.Rectangle(text_pos.x, text_pos.y + wm + 16, 100, 44)
      self._version_label.set_text(self._version_text[0])
      self._version_label.set_position(version_pos.x, version_pos.y)
      self._version_label.render()

      self._date_label.set_text(" " + self._version_text[3])
      self._date_label.set_position(version_pos.x + self._version_label.text_width + 10, version_pos.y)
      self._date_label.render()

      self._branch_label.set_max_width(gui_app.width - self._version_label.text_width - self._date_label.text_width - 32)
      self._branch_label.set_text(" " + ("release" if release_branch else self._version_text[1]))
      self._branch_label.set_position(version_pos.x + self._version_label.text_width + self._date_label.text_width + 20, version_pos.y)
      self._branch_label.render()

      y2 = version_pos.y + self._date_label.font_size + 7
      avail = self.rect.width - HOME_PADDING * 2
      row_w, lsz = draw_trip_row(gui_app.font(FontWeight.ROMAN), gui_app.font(FontWeight.DISPLAY), version_pos.x, y2, avail, self._day_txt, self._week_txt)
      self._trip_hit = rl.Rectangle(version_pos.x - 4, y2 - 4, min(avail, row_w) + 8, lsz * 1.16 + 8)

    # ***** Center-aligned bottom section icons *****
    usb_connected = ui_state.usb_connected
    usb_unknown = ui_state.usb_unknown
    chestnut_state = ui_state.chestnut_state
    # zoompilot's chestnut icons (sunnypilot/mici/layouts/home.py _set_chestnut_visibility),
    # which also show Jetlink: ui_state.chestnut_state is the link's with no chestnut fitted
    loading = chestnut_state == ChestnutState.LOADING
    # ready, and only a swap window away: steady rather than the loading pulse,
    # dim rather than the solid green of a model that is driving
    waiting = chestnut_state == ChestnutState.WAITING
    # downloading fills the dimmed icon, compiling flashes it; orange only for a real failure
    provisioning = ui_state.accel_progress is not None and chestnut_state != ChestnutState.DISCONNECTED
    chestnut_failed = not provisioning and chestnut_state in (ChestnutState.UNCOMPILED, ChestnutState.FAILED)
    self._usb_icon.set_visible(usb_connected and usb_unknown and not chestnut_failed and not provisioning)
    self._chestnut_fill_icon.set_visible(provisioning)
    self._chestnut_loading_icon.set_opacity(0.35 + 0.65 * (0.5 - 0.5 * math.cos(rl.get_time() * 6.0)))
    self._chestnut_loading_icon.set_visible(not provisioning and not usb_unknown and loading)
    self._chestnut_icon.set_opacity(0.5 if waiting else 1.0)
    self._chestnut_icon.set_visible(not provisioning and not usb_unknown and not loading and
                                    chestnut_state in (ChestnutState.READY, ChestnutState.ACTIVE, ChestnutState.WAITING))
    self._chestnut_failed_icon.set_visible(chestnut_failed)
    self._mic_icon.set_visible(ui_state.recording_audio)
    self._body_icon.set_visible(bool(ui_state.is_body))
    self._ssa_icon.set_visible(self._ssa_on and bool(ui_state.has_longitudinal_control))
    self._tits_badge.set_visible(self._tits_on)

    footer_rect = rl.Rectangle(self.rect.x + HOME_PADDING, self.rect.y + self.rect.height - 48, self.rect.width - HOME_PADDING, 48)
    self._status_bar_layout.render(footer_rect)
    if self._tits_badge.is_visible:
      r = self._tits_badge.rect
      self._tits_hit = rl.Rectangle(r.x - 8, r.y - 8, r.width + 16, r.height + 8)
    else:
      self._tits_hit = rl.Rectangle(0, 0, 0, 0)
    if self._ssa_icon.is_visible:
      r = self._ssa_icon.rect
      self._ssa_hit = rl.Rectangle(r.x - 8, r.y - 8, r.width + 16, r.height + 8)
    else:
      self._ssa_hit = rl.Rectangle(0, 0, 0, 0)
    # the accelerator icon opens Settings > Models
    accel = next((w for w in (self._chestnut_icon, self._chestnut_loading_icon, self._chestnut_failed_icon, self._chestnut_fill_icon)
                  if w.is_visible), None)
    self._accel_hit = rl.Rectangle(accel.rect.x - 8, accel.rect.y - 8, accel.rect.width + 16, accel.rect.height + 8) if accel else rl.Rectangle(0, 0, 0, 0)

    self._alerts_pill.set_position(self.rect.x + self.rect.width - self._alerts_pill.rect.width - HOME_PADDING,
                                   self.rect.y + self.rect.height - self._alerts_pill.rect.height)
    self._alerts_pill.render()
