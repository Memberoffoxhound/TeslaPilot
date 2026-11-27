import datetime
import time
import numpy as np
import raylib_nb as rl

from msgq.visionipc import VisionIpcClient
from openpilot.cereal.visionipc import VisionStreamType
from openpilot.common.constants import CV
from openpilot.selfdrive.navigation.helpers import latest_gps_source
from openpilot.selfdrive.navigation.renderer import EGO, ROUTE_INTENSITY, SIZE
from openpilot.selfdrive.ui.onroad.cameraview import CONNECTION_RETRY_INTERVAL
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FONT_SCALE, FontWeight, TextAlignment, TextAlignmentVertical, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel, gui_label

from openpilot.selfdrive.ui.layouts.settings.common import theme_rgb, THEME_OPENPILOT_RGB

PANEL_WIDTH = 261
STALE_SECONDS = 3
MARKER_MARGIN = 18  # pixels kept below the ego so its marker stays visible
# Maneuver row shares y=42 with the DM ink and compass pill. Original arrow/label mid was ~30.
NAV_ROW_CY = 42
NAV_HEADER_SHIFT = 12  # 42 - 30
NAV_MAP_TOP = 68  # 3px below the shifted header ink (was 61)

# AR overlay HUD, sized to read from 3 to 4 ft: 72 px digits are 6.1 mm at 300 PPI
AR_DIST_PX = 96 / FONT_SCALE
AR_UNIT_PX = 34 / FONT_SCALE
AR_STREET_PX = 30 / FONT_SCALE
AR_ETA_PX = (58 / FONT_SCALE, 46 / FONT_SCALE)  # alone, beside the set speed
AR_ETA_LABEL_PX = 18 / FONT_SCALE
AR_ETA_HIDE = 60.0  # m, the ETA steps aside for the turn
ETA_ROTATE = 4.0  # s per value

# Dim the white roads; the route intensity is tinted separately with the selected theme.
MAP_GREY = np.repeat(np.round(np.arange(256) * 0.45).astype(np.uint8)[:, None], 3, axis=1)


def _nav_theme_rgb() -> tuple[int, int, int]:
  # Selected theme (Tesla blue when LaneColor is tesla); stock/comma green if the theme manager is missing.
  try:
    return tuple(max(0, min(255, int(c))) for c in theme_rgb())
  except Exception:
    return THEME_OPENPILOT_RGB


def _nav_accent(alpha: float = 1.0) -> rl.Color:
  r, g, b = _nav_theme_rgb()
  return rl.Color(r, g, b, int(max(0.0, min(1.0, float(alpha))) * 255))


def _map_colors() -> np.ndarray:
  colors = MAP_GREY.copy()
  colors[ROUTE_INTENSITY - 1:ROUTE_INTENSITY + 2] = _nav_theme_rgb()
  return colors


def format_distance(meters: float) -> str:
  """m / ft under 1000 m / 300 m, km / mi beyond."""
  if ui_state.is_metric:
    return f'{round(meters / 10) * 10} m' if meters < 1000 else f'{meters / 1000:.1f} km'
  return f'{round(meters * CV.METER_TO_FOOT / 50) * 50} ft' if meters < 300 else f'{meters * CV.METER_TO_MILE:.1f} mi'


class NavigationPanel(Widget):
  """Turn instructions around the map frames mapsd publishes for the model."""

  def __init__(self):
    super().__init__()
    self._client = VisionIpcClient('mapsd', VisionStreamType.VISION_STREAM_MAP, True)
    self._last_connect = 0.0
    self._frame_time = 0.0
    self._texture = None
    self._eta_label = UnifiedLabel('', 34, FontWeight.BOLD, rl.WHITE, scroll=True)
    self._muted = rl.Color(162, 175, 185, 255)

  def _update_state(self):
    if not self._client.is_connected():
      if rl.get_time() - self._last_connect < CONNECTION_RETRY_INTERVAL:
        return
      self._last_connect = rl.get_time()
      if not self._client.connect(False) or not self._client.num_buffers:
        return
      self._unload_texture()
      self._texture = rl.load_texture_from_image(rl.Image(None, SIZE, SIZE, 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8))
    frame = self._client.recv(timeout_ms=0)
    if frame is not None:
      gray = np.frombuffer(frame.data, dtype=np.uint8, count=SIZE * SIZE)
      rl.update_texture(self._texture, _map_colors()[gray])
      # Without a usable map, mapsd publishes black frames with a zero timestamp.
      self._frame_time = rl.get_time() if self._client.timestamp_sof else 0.0

  @property
  def routing(self):
    return ui_state.sm.valid['navInstruction'] and ui_state.sm.alive['navInstruction']

  @property
  def map_ready(self):
    return self._texture is not None and 0 <= rl.get_time() - self._frame_time < STALE_SECONDS

  def _draw_status(self, rect):
    """What the map is waiting on, in place of the map."""
    statuses = (
      ('GPS fix', latest_gps_source(ui_state.sm) is not None),
      ('Route', self.routing),
      ('Map frames', self.map_ready),
    )
    for i, (name, ok) in enumerate(statuses):
      gui_label(rl.Rectangle(rect.x + 10, rect.y + 12 + i * 28, rect.width - 20, 26), f'{name}: {"yes" if ok else "no"}', 22,
                _nav_accent() if ok else self._muted, FontWeight.MEDIUM, alignment_vertical=TextAlignmentVertical.TOP)

  def _render(self, rect):
    x, y = rect.x, rect.y
    rl.draw_rectangle_rec(rect, rl.Color(7, 13, 18, 255))
    instruction = ui_state.sm['navInstruction']
    if self.routing:
      direction = instruction.maneuverModifier
      flip = -1 if 'left' in direction else 1
      # The maneuver arrow on a 1.4x grid, centered in the header's icon box, with round joins for the thick stroke.
      if direction in ('straight', ''):
        shape = [(0, 14), (0, -12), (-6, -5), (0, -12), (6, -5)]
      else:
        shape = [(-flip*9, 14), (-flip*9, -4), (-flip*2, -9), (flip*9, -9), (flip*3, -15), (flip*9, -9), (flip*3, -3)]
      points = [rl.Vector2(x + 31 + 1.4*px, y + NAV_ROW_CY + 1.4*py) for px, py in shape]
      for a, b in zip(points[:-1], points[1:], strict=True):
        rl.draw_line_ex(a, b, 7, _nav_accent())
      for point in points:
        rl.draw_circle_v(point, 3.5, _nav_accent())
      gui_label(rl.Rectangle(x+64, y+11+NAV_HEADER_SHIFT, rect.width-72, 40),
                format_distance(max(0, instruction.maneuverDistance)), 34, rl.WHITE, FontWeight.BOLD,
                alignment_vertical=TextAlignmentVertical.TOP)
    else:
      gui_label(rl.Rectangle(x+12, y+NAV_ROW_CY-15, rect.width-24, 30), 'Waiting for route', 26, rl.WHITE, FontWeight.BOLD,
                alignment_vertical=TextAlignmentVertical.TOP)
    map_rect = rl.Rectangle(x+8, y+NAV_MAP_TOP, rect.width-16, rect.height-50-NAV_MAP_TOP)
    rl.draw_rectangle_rec(map_rect, rl.BLACK)
    if self.map_ready:
      # A 1:1 crop of the model's frame, centered horizontally with the ego near the bottom.
      width, height = min(map_rect.width, SIZE), min(map_rect.height, SIZE)
      source = rl.Rectangle((SIZE - width) // 2, min(SIZE - height, max(0, EGO[1] + MARKER_MARGIN - height)), width, height)
      target = rl.Rectangle(map_rect.x + (map_rect.width - width) / 2, map_rect.y + map_rect.height - height, width, height)
      rl.draw_texture_pro(self._texture, source, target, rl.Vector2(0, 0), 0, rl.WHITE)
    else:
      self._draw_status(map_rect)
    if self.routing:
      seconds = max(0, instruction.timeRemaining)
      remaining = max(0, instruction.distanceRemaining)
      self._eta_label.set_text(f'{max(1, round(seconds / 60))} min / {format_distance(remaining)}')
      self._eta_label.render(rl.Rectangle(x+9, y+rect.height-45, rect.width-18, 40))

  def _eta_values(self, instruction) -> list[tuple[str, str]]:
    seconds = max(0, instruction.timeRemaining)
    arrive = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
    return [('arrive', f'{(arrive.hour - 1) % 12 + 1}:{arrive.minute:02d}'), ('time left', f'{max(1, round(seconds / 60))} min'),
            ('distance', format_distance(max(0, instruction.distanceRemaining)))]

  def render_ar(self, rect, speed_alpha: float):
    # big turn card on the camera for the AR view; only distance, arrow and one street name are large
    if not self.routing:
      return
    instruction = ui_state.sm['navInstruction']
    accent = _nav_accent()
    tile = rl.Rectangle(rect.x + 2, rect.y + 8, 98, 98)
    rl.draw_rectangle_rounded(tile, 0.2, 10, accent)
    direction = instruction.maneuverModifier
    flip = -1 if 'left' in direction else 1
    if direction in ('straight', ''):
      shape = [(0, 14), (0, -12), (-6, -5), (0, -12), (6, -5)]
    else:
      shape = [(-flip*9, 14), (-flip*9, -4), (-flip*2, -9), (flip*9, -9), (flip*3, -15), (flip*9, -9), (flip*3, -3)]
    cx, cy = tile.x + tile.width / 2, tile.y + tile.height / 2 + 2
    points = [rl.Vector2(cx + 3.0 * px, cy + 3.0 * py) for px, py in shape]
    dark = rl.Color(6, 10, 8, 255)
    for a, b in zip(points[:-1], points[1:], strict=True):
      rl.draw_line_ex(a, b, 14, dark)
    for point in points:
      rl.draw_circle_v(point, 7, dark)
    dist = format_distance(max(0, instruction.maneuverDistance)) if instruction.maneuverDistance >= 15 else 'Now'
    value, _, unit = dist.partition(' ')
    gui_label(rl.Rectangle(rect.x, rect.y + 96, 260, 100), value, AR_DIST_PX, rl.WHITE, FontWeight.BOLD,
              alignment_vertical=TextAlignmentVertical.TOP)
    if unit:
      vw = measure_text_cached(gui_app.font(FontWeight.BOLD), value, AR_DIST_PX).x
      gui_label(rl.Rectangle(rect.x + vw + 5, rect.y + 150, 80, 40), unit, AR_UNIT_PX, rl.Color(220, 226, 232, 255), FontWeight.BOLD,
                alignment_vertical=TextAlignmentVertical.TOP)
    street = instruction.maneuverPrimaryText
    gui_label(rl.Rectangle(rect.x + 2, rect.y + rect.height - 40, 300, 36), street, AR_STREET_PX, rl.Color(235, 240, 245, 255), FontWeight.BOLD,
              alignment_vertical=TextAlignmentVertical.TOP)
    if instruction.maneuverDistance < AR_ETA_HIDE:
      return
    label, val = self._eta_values(instruction)[int(time.monotonic() / ETA_ROTATE) % 3]
    size = AR_ETA_PX[1] if speed_alpha > 0.5 else AR_ETA_PX[0]
    font = gui_app.font(FontWeight.BOLD)
    w = max(measure_text_cached(font, val, size).x, measure_text_cached(font, label, AR_ETA_LABEL_PX).x) + 26
    h = size * FONT_SCALE + 34
    box = rl.Rectangle(rect.x + rect.width - 8 - w, rect.y + rect.height - 6 - h, w, h)
    rl.draw_rectangle_rounded(box, 0.3, 10, rl.Color(10, 14, 18, 220))
    gui_label(rl.Rectangle(box.x + 13, box.y + 4, w, 24), label, AR_ETA_LABEL_PX, self._muted, FontWeight.BOLD,
              alignment_vertical=TextAlignmentVertical.TOP)
    gui_label(rl.Rectangle(box.x + 12, box.y + 24, w, h - 24), val, size, rl.WHITE, FontWeight.BOLD,
              alignment=TextAlignment.LEFT, alignment_vertical=TextAlignmentVertical.TOP)

  def _unload_texture(self):
    if self._texture:
      rl.unload_texture(self._texture)
      self._texture = None

  def close(self):
    self._unload_texture()
