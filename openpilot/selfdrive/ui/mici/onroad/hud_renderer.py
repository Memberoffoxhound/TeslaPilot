import math
import numpy as np
import raylib_nb as rl
from dataclasses import dataclass
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.mici.onroad import DIMMED_ICON_ALPHA
from openpilot.selfdrive.ui.mici.onroad.status import STATUS_FADE_RC, lerp_color, status_fade, steer_fade
from openpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus, ChestnutState
from openpilot.selfdrive.ui.mici.widgets.fill_icon import draw_progress
from openpilot.selfdrive.ui.layouts.settings.common import (
  custom_onroad_ui, heading_deg, heading_letter, compass_size, COMPASS_LARGE,
  tesla_theme, theme_color, theme_rgb, THEME_TESLA_RGB,
)
from openpilot.system.ui.lib.application import gui_app, FontWeight, ASSETS_DIR
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.common.filter_simple import FirstOrderFilter


# Constants
SET_SPEED_NA = 255
KM_TO_MILE = 0.621371
CRUISE_DISABLED_CHAR = '–'

SET_SPEED_PERSISTENCE = 2.5  # seconds
COMPASS_FULL_ALPHA = 229.5
COMPASS_TOP = 10  # dm icon top: 52 px centered 36 down
COMPASS_RIGHT = 4
SLOT_CX, SLOT_CY = 42, 50  # gpu icon center from the video's bottom right with the small compass, on the personality
SLOT_SHOW, SLOT_PEEK, SLOT_FAILED, SLOT_COMPILE_EVERY = 3.0, 2.0, 4.0, 30.0  # s, how long it takes the slot
WHEEL_SIZE = 52
WHEEL_WHITE = rl.Color(255, 255, 255, 255)
WHEEL_GREEN = rl.Color(0, 255, 64, 255)
WHEEL_ORANGE = rl.Color(255, 115, 0, 255)
WHEEL_RIM_R = 0.77
MADS_PAUSED_ALPHA = 0.45
MADS_HUB_ALPHA = 0.85


def _texture(rgba: np.ndarray, px: float) -> rl.Texture:
  texture = rl.load_texture_from_image(rl.Image(None, rgba.shape[1], rgba.shape[0], 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8))
  rl.update_texture(texture, np.ascontiguousarray(rgba))
  rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
  texture.width, texture.height = round(rgba.shape[1] / px), round(rgba.shape[0] / px)
  return texture


def _wheel_effect_textures(asset: str, size: int) -> tuple[rl.Texture, rl.Texture]:
  """White glow and center highlight for the wheel, matching the design's render. Tint the glow when drawing."""
  image = gui_app._load_image_from_path((ASSETS_DIR / asset).as_posix(), size, size)
  w, h, px = image.width, image.height, image.width / size
  alpha = np.frombuffer(image.to_bytes(w * h * 4), dtype=np.uint8).reshape(h, w, 4)[..., 3] / 255.0
  rl.unload_image(image)

  # glow: Figma's drop shadow (blur 24 at 128px) renders as a gaussian with sigma 10, its spread is ignored on vectors
  sigma = 10 * size / 128 * px
  pad = math.ceil(3 * sigma)
  glow = np.pad(alpha, pad)
  x = np.arange(-pad, pad + 1)
  kernel = np.exp(-x ** 2 / (2 * sigma ** 2))
  kernel /= kernel.sum()
  for axis in (0, 1):
    glow = np.apply_along_axis(np.convolve, axis, glow, kernel, mode='same')
  glow_rgba = np.full((*glow.shape, 4), 255, dtype=np.uint8)
  glow_rgba[..., 3] = np.clip(glow * 255, 0, 255)

  # highlight: the fill is a radial gradient from 35% lighter at the center to the base color at the rim
  yy, xx = np.mgrid[:h, :w]
  r = np.hypot(xx + 0.5 - w / 2, yy + 0.5 - h / 2) / (w / 2)
  highlight_rgba = np.full((h, w, 4), 255, dtype=np.uint8)
  highlight_rgba[..., 3] = np.clip(alpha * 89 * (1 - r), 0, 255)

  return _texture(glow_rgba, px), _texture(highlight_rgba, px)


def _wheel_part_textures(asset: str, size: int) -> tuple[rl.Texture, rl.Texture]:
  # MADS wheel: rim is steering, hub and spokes are speed
  image = gui_app._load_image_from_path((ASSETS_DIR / asset).as_posix(), size, size)
  w, h, px = image.width, image.height, image.width / size
  alpha = np.frombuffer(image.to_bytes(w * h * 4), dtype=np.uint8).reshape(h, w, 4)[..., 3]
  rl.unload_image(image)
  yy, xx = np.mgrid[:h, :w]
  rim = np.hypot(xx + 0.5 - w / 2, yy + 0.5 - h / 2) / (w / 2) > WHEEL_RIM_R
  parts = []
  for keep in (rim, ~rim):
    rgba = np.full((h, w, 4), 255, dtype=np.uint8)
    rgba[..., 3] = alpha * keep
    parts.append(_texture(rgba, px))
  return parts[0], parts[1]


@dataclass(frozen=True)
class FontSizes:
  current_speed: int = 176
  speed_unit: int = 66
  max_speed: int = 36
  set_speed: int = 112


@dataclass(frozen=True)
class Colors:
  WHITE = rl.WHITE
  WHITE_TRANSLUCENT = rl.Color(255, 255, 255, 200)


FONT_SIZES = FontSizes()
COLORS = Colors()


class HudRenderer(Widget):
  def __init__(self):
    super().__init__()
    """Initialize the HUD renderer."""
    self.is_cruise_set: bool = False
    self.is_cruise_available: bool = True
    self.set_speed: float = SET_SPEED_NA
    self._set_speed_changed_time: float = 0
    self.speed: float = 0.0
    self.v_ego_cluster_seen: bool = False
    self._engaged: bool = False
    self._chestnut_fade_time: float = 0

    self._can_draw_top_icons = True
    self._show_wheel_critical = False

    self._font_bold: rl.Font = gui_app.font(FontWeight.BOLD)
    self._font_medium: rl.Font = gui_app.font(FontWeight.MEDIUM)
    self._font_semi_bold: rl.Font = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_display: rl.Font = gui_app.font(FontWeight.DISPLAY)

    self._torque_bar = TorqueBar()

    self._txt_wheel: rl.Texture = gui_app.texture('icons_mici/wheel.png', WHEEL_SIZE, WHEEL_SIZE)
    self._txt_wheel_glow, self._txt_wheel_highlight = _wheel_effect_textures('icons_mici/wheel.png', WHEEL_SIZE)
    self._txt_wheel_rim, self._txt_wheel_hub = _wheel_part_textures('icons_mici/wheel.png', WHEEL_SIZE)
    self._txt_chestnut: rl.Texture = gui_app.texture('icons_mici/chestnut.png', 48, 36)
    self._txt_chestnut_green: rl.Texture = gui_app.texture('icons_mici/chestnut_green.png', 48, 36)
    self._txt_chestnut_orange: rl.Texture = gui_app.texture('icons_mici/chestnut_orange.png', 61, 36)
    self._chestnut_icon: rl.Texture | None = None
    self._txt_compass_bg: rl.Texture = gui_app.texture('icons_mici/onroad/driver_monitoring/dm_background.png', 60, 60)
    self._txt_compass_fan: rl.Texture = gui_app.texture('icons_mici/onroad/driver_monitoring/dm_cone.png', 52, 52)
    self._txt_compass_bg90: rl.Texture = gui_app.texture('icons_mici/onroad/driver_monitoring/dm_background.png', 90, 90)
    self._txt_compass_fan90: rl.Texture = gui_app.texture('icons_mici/onroad/driver_monitoring/dm_cone.png', 78, 78)
    self._compass_letter: str | None = None
    self._heading_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps, initialized=False)
    # small fades like the long indicator, large like MAX
    self._compass_fade = (FirstOrderFilter(0.0, 0.05, 1 / gui_app.target_fps), FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps))
    self._wheel_critical_filter = FirstOrderFilter(0, STATUS_FADE_RC, 1 / gui_app.target_fps)

    self._set_speed_alpha_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    self._set_speed_alpha = 0.0
    self._chestnut_alpha_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    # shared slot with the small compass: personality alpha and highlight, show timer
    self._slot_partner = (0.0, False)
    self._slot_want = False
    self._slot_key: tuple | None = None
    self._slot_step: int | None = None
    self._slot_until = self._slot_last = self._slot_t = 0.0

  def set_wheel_critical_icon(self, critical: bool):
    """Set the wheel icon to critical or normal state."""
    self._show_wheel_critical = critical

  def set_torque_bar_hidden(self, hidden: bool):
    self._torque_bar.set_hidden(hidden)

  def set_can_draw_top_icons(self, can_draw_top_icons: bool):
    """Set whether to draw the top part of the HUD."""
    self._can_draw_top_icons = can_draw_top_icons

  def set_slot_partner(self, alpha: float, highlight: bool) -> None:
    self._slot_partner = (alpha, highlight)

  def slot_busy(self) -> bool:
    return self._slot_want or self._chestnut_alpha_filter.x > 1e-2

  def set_speed_alpha(self) -> float:
    return self._set_speed_alpha

  def drawing_top_icons(self) -> bool:
    # whether we're drawing any top icons currently
    return bool(self._set_speed_alpha > 1e-2)

  def _update_state(self) -> None:
    """Update HUD state based on car state and controls state."""
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      self.is_cruise_set = False
      self.set_speed = SET_SPEED_NA
      self.speed = 0.0
      return

    car_state = sm['carState']

    set_speed = car_state.vCruiseCluster
    engaged = sm['selfdriveState'].enabled
    if (set_speed != self.set_speed and engaged) or (engaged and not self._engaged):
      self._set_speed_changed_time = rl.get_time()
    if engaged != self._engaged:
      self._chestnut_fade_time = rl.get_time() if engaged else 0
    self._engaged = engaged
    self.set_speed = set_speed
    self.is_cruise_set = 0 < self.set_speed < SET_SPEED_NA
    self.is_cruise_available = self.set_speed != -1

    v_ego_cluster = car_state.vEgoCluster
    self.v_ego_cluster_seen = self.v_ego_cluster_seen or v_ego_cluster != 0.0
    v_ego = v_ego_cluster if self.v_ego_cluster_seen else car_state.vEgo
    speed_conversion = CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH
    self.speed = max(0.0, v_ego * speed_conversion)

  def _render(self, rect: rl.Rectangle) -> None:
    """Render HUD elements to the screen."""

    self._torque_bar.render(rect)

    if self.is_cruise_set:
      self._draw_set_speed(rect)

    self._draw_model_source(rect)
    self._draw_compass(rect)

  def render_small_compass(self, rect: rl.Rectangle, visible: bool) -> None:
    self._draw_compass(rect, visible)

  def render_steering_wheel(self, rect: rl.Rectangle) -> None:
    """Draw the steering wheel centered at the bottom of rect, after render() has updated state."""
    self._draw_steering_wheel(rect)

  def _draw_model_source(self, rect: rl.Rectangle) -> None:
    custom = custom_onroad_ui()
    shared = custom and compass_size() != COMPASS_LARGE
    # custom ui: under alerts like MAX
    top_ok = self._can_draw_top_icons or not custom
    now, progress, state = rl.get_time(), ui_state.accel_progress, ui_state.chestnut_state
    # leftover compile/download must not flash once the device is gone
    if state == ChestnutState.DISCONNECTED:
      self._slot_want, self._chestnut_alpha_filter.x = False, 0.0
      return
    loading = progress is None and state == ChestnutState.LOADING
    failed = progress is None and state in (ChestnutState.UNCOMPILED, ChestnutState.FAILED)
    if progress is not None:
      icon, opacity = self._txt_chestnut, 1.0
    elif loading:
      icon = self._txt_chestnut
      opacity = 0.35 + 0.65 * (0.5 - 0.5 * math.cos(now * 6.0))
    elif failed:
      icon, opacity = self._txt_chestnut_orange, 1.0
    elif state == ChestnutState.ACTIVE:
      icon = self._txt_chestnut_green
      # custom ui: dims disengaged like the wheel
      opacity = 1 - (1 - DIMMED_ICON_ALPHA) * status_fade.weight(UIStatus.DISENGAGED) if custom else 1.0
    else:
      self._slot_want, self._chestnut_alpha_filter.x = False, 0.0
      return

    if icon is not self._chestnut_icon:
      self._chestnut_fade_time = now
      self._chestnut_icon = icon
    if shared:
      visible = self._slot_visible(now, state, progress, failed, loading)
    else:
      visible = progress is not None or loading or now - self._chestnut_fade_time < SET_SPEED_PERSISTENCE
    self._slot_want = shared and visible and top_ok
    # shared: in only once the personality is out, out at once on a personality change
    alpha = self._chestnut_alpha_filter.update(visible and top_ok and not (shared and self._slot_partner[0] > 1e-2))
    if shared and self._slot_partner[1]:
      alpha = self._chestnut_alpha_filter.x = 0.0
    if alpha < 1e-2:
      return

    x, y = self._model_source_pos(rect, icon, custom)
    if not draw_progress(icon, x, y, alpha):
      rl.draw_texture_ex(icon, rl.Vector2(x, y), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * opacity * alpha)))

  def _slot_visible(self, now: float, state, progress, failed: bool, compiling: bool) -> bool:
    # short shows at drive start and changes, peeks on progress, then the personality gets the slot back
    dt, self._slot_t = min(max(now - self._slot_t, 0.0), 0.1), now
    kind, frac = progress or (None, None)
    step = int(frac * 4) if kind == 'download' and frac is not None else None
    key = (ui_state.started_frame, state, kind)

    def show(d: float) -> None:
      self._slot_until, self._slot_last = max(self._slot_until, now + d), now

    if key != self._slot_key:
      show(SLOT_FAILED if failed else SLOT_SHOW)
    elif step != self._slot_step:
      show(SLOT_PEEK)
    elif (compiling or kind == 'compile') and now - self._slot_last >= SLOT_COMPILE_EVERY:
      show(SLOT_PEEK)
    self._slot_key, self._slot_step = key, step
    # a personality change wins, what's left of a show waits for it
    if self._slot_partner[1]:
      if self._slot_until > now:
        self._slot_until += dt
      return False
    return now < self._slot_until

  @staticmethod
  def _model_source_pos(rect: rl.Rectangle, icon: rl.Texture, custom: bool) -> tuple[float, float]:
    # stock bottom left, custom bottom right clear of the ball and torque bar, small compass on the personality
    r, b = rect.x + rect.width, rect.y + rect.height
    if not custom:
      return rect.x + 14, b - 10 - icon.height
    if compass_size() != COMPASS_LARGE:
      return r - SLOT_CX - icon.width / 2, b - SLOT_CY - icon.height / 2
    return r - 10 - icon.width, b - 10 - icon.height

  def _draw_steering_wheel(self, rect: rl.Rectangle) -> None:
    # The wheel is the source of truth for engagement: green if and only if openpilot is engaged.
    # When disengaged it's grayed out, except for steerRequired alerts which show it orange.
    critical = self._wheel_critical_filter.update(self._show_wheel_critical)
    idle_color = lerp_color(WHEEL_WHITE, WHEEL_ORANGE, critical)
    green = rl.Color(*THEME_TESLA_RGB, 255) if tesla_theme() else WHEEL_GREEN
    wheel_color = status_fade.color({UIStatus.ENGAGED: green, UIStatus.OVERRIDE: idle_color, UIStatus.DISENGAGED: idle_color})
    engaged = status_fade.weight(UIStatus.ENGAGED)
    glow = engaged + (1 - engaged) * critical
    wheel_txt = self._txt_wheel

    # pos
    pos_x = int(rect.x + rect.width / 2)
    pos_y = int(rect.y + rect.height - 10 - wheel_txt.height / 2)
    rotation = -ui_state.sm['carState'].steeringAngleDeg if ui_state.started else 0.0

    alpha = 255 * (1 - (1 - DIMMED_ICON_ALPHA) * status_fade.weight(UIStatus.DISENGAGED) * (1 - critical))
    mads = ui_state.sm['selfdriveStateSP'].mads
    if ui_state.started and mads.enabled and not ui_state.engaged and critical < 0.5:
      self._draw_mads_wheel(pos_x, pos_y, rotation, mads.active)
      return
    origin = rl.Vector2(self._txt_wheel_glow.width / 2, self._txt_wheel_glow.height / 2)
    rl.draw_texture_pro(self._txt_wheel_glow, rl.Rectangle(0, 0, self._txt_wheel_glow.width, self._txt_wheel_glow.height),
                        rl.Rectangle(pos_x, pos_y, self._txt_wheel_glow.width, self._txt_wheel_glow.height), origin, rotation,
                        rl.Color(wheel_color.r, wheel_color.g, wheel_color.b, int(alpha * glow)))
    rl.draw_texture_pro(wheel_txt, rl.Rectangle(0, 0, wheel_txt.width, wheel_txt.height),
                        rl.Rectangle(pos_x, pos_y, wheel_txt.width, wheel_txt.height),
                        rl.Vector2(wheel_txt.width / 2, wheel_txt.height / 2), rotation, rl.Color(wheel_color.r, wheel_color.g, wheel_color.b, int(alpha)))
    rl.draw_texture_pro(self._txt_wheel_highlight, rl.Rectangle(0, 0, wheel_txt.width, wheel_txt.height),
                        rl.Rectangle(pos_x, pos_y, wheel_txt.width, wheel_txt.height),
                        rl.Vector2(wheel_txt.width / 2, wheel_txt.height / 2), rotation, rl.Color(255, 255, 255, int(alpha * glow)))

  def _draw_mads_wheel(self, pos_x: int, pos_y: int, rotation: float, active: bool) -> None:
    # MADS steering alone: rim in the theme color (comma green fallback), hub white; paused dims both
    r, g, b = theme_rgb()
    rim_alpha = 255 if active else int(255 * MADS_PAUSED_ALPHA)
    hub_alpha = int(255 * (MADS_HUB_ALPHA if active else DIMMED_ICON_ALPHA))
    dst = rl.Rectangle(pos_x, pos_y, self._txt_wheel_rim.width, self._txt_wheel_rim.height)
    src = rl.Rectangle(0, 0, self._txt_wheel_rim.width, self._txt_wheel_rim.height)
    origin = rl.Vector2(self._txt_wheel_rim.width / 2, self._txt_wheel_rim.height / 2)
    if active:
      glow = self._txt_wheel_glow
      rl.draw_texture_pro(glow, rl.Rectangle(0, 0, glow.width, glow.height), rl.Rectangle(pos_x, pos_y, glow.width, glow.height),
                          rl.Vector2(glow.width / 2, glow.height / 2), rotation, rl.Color(r, g, b, 255))
    rl.draw_texture_pro(self._txt_wheel_rim, src, dst, origin, rotation, rl.Color(r, g, b, rim_alpha))
    rl.draw_texture_pro(self._txt_wheel_hub, src, dst, origin, rotation, rl.Color(255, 255, 255, hub_alpha))

  def _draw_compass(self, rect: rl.Rectangle, panel_visible: bool | None = None) -> None:
    # large draws from render(), small from the side panel
    large = compass_size() == COMPASS_LARGE
    if large == (panel_visible is not None):
      return
    letter, deg = heading_letter(), heading_deg()
    if letter:
      self._compass_letter = letter
    if deg is not None:
      cur = self._heading_filter.x
      self._heading_filter.x = self._heading_filter.update(cur + (deg - cur + 180.0) % 360.0 - 180.0) % 360.0
    heading, letter = self._heading_filter.x, self._compass_letter

    custom = custom_onroad_ui()
    # large sits under alerts and fades out disengaged like MAX, small dims like the other panel icons
    shown = custom and (self._can_draw_top_icons if large else bool(panel_visible))
    disengaged = steer_fade.weight(UIStatus.DISENGAGED)
    dim = 1 - disengaged if large else 1 - (1 - DIMMED_ICON_ALPHA / 0.9) * disengaged
    a = int(255 * 0.9 * self._compass_fade[large].update(float(shown)) * dim)
    if not custom or a < 3:
      return
    if large:
      size, fan, sz = 90, 78, 42
      cx, cy = rect.x + rect.width - COMPASS_RIGHT - size / 2, rect.y + COMPASS_TOP + size / 2
      bg, fan_tex = self._txt_compass_bg90, self._txt_compass_fan90
    else:
      size, fan, sz = 60, 52, 28
      cx, cy = rect.x + rect.width / 2, rect.y + rect.height / 2
      bg, fan_tex = self._txt_compass_bg, self._txt_compass_fan
    fade = rl.Color(255, 255, 255, a)
    rl.draw_texture_ex(bg, rl.Vector2(cx - size / 2, cy - size / 2), 0.0, 1.0, fade)
    rl.draw_texture_pro(fan_tex, rl.Rectangle(0, 0, fan_tex.width, fan_tex.height), rl.Rectangle(cx, cy, fan, fan),
                        rl.Vector2(fan / 2, fan / 2), heading, theme_color(a / 255.0))
    rl.draw_ring(rl.Vector2(cx, cy), fan / 2 + 1, fan / 2 + 3, 0, 360, 36, rl.Color(255, 255, 255, int(255 * 0.25 * (a / COMPASS_FULL_ALPHA))))
    if not letter:
      return
    ts = measure_text_cached(self._font_bold, letter, sz)
    while ts.x > size * 0.62 and sz > 12:
      sz -= 1
      ts = measure_text_cached(self._font_bold, letter, sz)
    rl.draw_text_ex(self._font_bold, letter, rl.Vector2(cx - ts.x / 2, cy - ts.y / 2), sz, 0, fade)

  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    """Draw the MAX speed indicator box."""
    alpha = self._set_speed_alpha_filter.update(0 < rl.get_time() - self._set_speed_changed_time < SET_SPEED_PERSISTENCE and self._can_draw_top_icons)
    alpha = self._set_speed_alpha = alpha * (1 - status_fade.weight(UIStatus.DISENGAGED))
    if alpha < 1e-2:
      return

    x = rect.x
    y = rect.y

    # draw drop shadow
    circle_radius = 162 // 2
    rl.draw_circle_gradient(rl.Vector2(x + circle_radius, y + circle_radius), circle_radius,
                            rl.Color(0, 0, 0, int(255 / 2 * alpha)), rl.BLANK)

    set_speed_color = rl.Color(255, 255, 255, int(255 * 0.9 * alpha))
    max_color = rl.Color(255, 255, 255, int(255 * 0.9 * alpha))

    set_speed = self.set_speed
    if self.is_cruise_set and not ui_state.is_metric:
      set_speed *= KM_TO_MILE

    set_speed_text = CRUISE_DISABLED_CHAR if not self.is_cruise_set else str(round(set_speed))
    rl.draw_text_ex(
      self._font_display,
      set_speed_text,
      rl.Vector2(x + 13 + 4, y + 3 - 8 - 3 + 4),
      FONT_SIZES.set_speed,
      0,
      set_speed_color,
    )

    max_text = tr("MAX")
    rl.draw_text_ex(
      self._font_semi_bold,
      max_text,
      rl.Vector2(x + 25, y + FONT_SIZES.set_speed - 7 + 4),
      FONT_SIZES.max_speed,
      0,
      max_color,
    )

  def _draw_current_speed(self, rect: rl.Rectangle) -> None:
    """Draw the current vehicle speed and unit."""
    speed_text = str(round(self.speed))
    speed_text_size = measure_text_cached(self._font_bold, speed_text, FONT_SIZES.current_speed)
    speed_pos = rl.Vector2(rect.x + rect.width / 2 - speed_text_size.x / 2, 180 - speed_text_size.y / 2)
    rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, COLORS.WHITE)

    unit_text = tr("km/h") if ui_state.is_metric else tr("mph")
    unit_text_size = measure_text_cached(self._font_medium, unit_text, FONT_SIZES.speed_unit)
    unit_pos = rl.Vector2(rect.x + rect.width / 2 - unit_text_size.x / 2, 290 - unit_text_size.y / 2)
    rl.draw_text_ex(self._font_medium, unit_text, unit_pos, FONT_SIZES.speed_unit, 0, COLORS.WHITE_TRANSLUCENT)
