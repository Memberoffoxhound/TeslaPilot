import datetime
import time
import numpy as np
import raylib_nb as rl

from openpilot.selfdrive.ui.mici.onroad.navigation import format_distance
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FONT_SCALE, FontWeight, TextAlignment, TextAlignmentVertical, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.label import gui_label

# AR overlay HUD, sized to read from 3 to 4 ft: 72 px digits are 6.1 mm at 300 PPI
AR_DIST_PX = 96 / FONT_SCALE
AR_UNIT_PX = 34 / FONT_SCALE
AR_STREET_PX = 36 / FONT_SCALE
AR_ETA_PX = 64 / FONT_SCALE
AR_ETA_VIGNETTE = 230  # px radius of the corner gradient
AR_ETA_LABEL_PX = 26 / FONT_SCALE
AR_TILE_X = 60  # px, the turn card stays in the top left (DM is in the top right)
AR_BAR_X = 166  # px, the maneuver progress bar beside the card
AR_ETA_HIDE = 60.0  # m, the ETA steps aside for the turn
ETA_ROTATE = 4.0  # s per value
COMMA_GREEN = (23, 127, 64)


def _accent_rgb() -> tuple[int, int, int]:
  # selected lane color from the theme manager, else comma green
  try:
    from openpilot.selfdrive.ui.layouts.settings.common import theme_rgb
    return tuple(max(0, min(255, int(c))) for c in theme_rgb())
  except Exception:
    try:
      from openpilot.selfdrive.ui.layouts.settings.common import THEME_OPENPILOT_RGB
      return tuple(THEME_OPENPILOT_RGB)
    except Exception:
      return COMMA_GREEN


def _accent(alpha: float = 1.0) -> rl.Color:
  r, g, b = _accent_rgb()
  return rl.Color(r, g, b, int(max(0.0, min(1.0, float(alpha))) * 255))


def _eta_values(instruction) -> list[tuple[str, str]]:
  seconds = max(0, instruction.timeRemaining)
  arrive = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
  return [('arrive', f'{(arrive.hour - 1) % 12 + 1}:{arrive.minute:02d}'), ('time left', f'{max(1, round(seconds / 60))} min'),
          ('distance', format_distance(max(0, instruction.distanceRemaining)))]


class NavARHud:
  # big turn card, distance, street and ETA on the camera for the AR view
  def __init__(self):
    self._man_key = ''
    self._man_start = 1.0

  def render(self, rect):
    if not (ui_state.sm.valid['navInstruction'] and ui_state.sm.alive['navInstruction']):
      return
    instruction = ui_state.sm['navInstruction']
    accent = _accent()
    rl.draw_rectangle_gradient_h(int(rect.x), int(rect.y), 300, int(rect.height), rl.Color(4, 6, 8, 215), rl.BLANK)
    tile = rl.Rectangle(rect.x + AR_TILE_X, rect.y + 8, 98, 98)
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
    key = f'{instruction.maneuverPrimaryText}|{instruction.maneuverType}'
    if key != self._man_key or instruction.maneuverDistance > self._man_start:
      self._man_key, self._man_start = key, max(instruction.maneuverDistance, 1.0)
    progress = float(np.clip(1 - instruction.maneuverDistance / self._man_start, 0, 1))
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x + AR_BAR_X, tile.y + 4, 6, 90), 1.0, 4, rl.Color(255, 255, 255, 50))
    if progress > 0.01:
      rl.draw_rectangle_rounded(rl.Rectangle(rect.x + AR_BAR_X, tile.y + 4 + 90 * (1 - progress), 6, 90 * progress), 1.0, 4, accent)
    dist = format_distance(max(0, instruction.maneuverDistance)) if instruction.maneuverDistance >= 15 else 'Now'
    value, _, unit = dist.partition(' ')
    gui_label(rl.Rectangle(rect.x - 2, rect.y + 96, 260, 100), value, AR_DIST_PX, rl.WHITE, FontWeight.BOLD,
              alignment_vertical=TextAlignmentVertical.TOP)
    if unit:
      vw = measure_text_cached(gui_app.font(FontWeight.BOLD), value, AR_DIST_PX).x
      gui_label(rl.Rectangle(rect.x + vw + 1, rect.y + 150, 80, 40), unit, AR_UNIT_PX, rl.Color(220, 226, 232, 255), FontWeight.BOLD,
                alignment_vertical=TextAlignmentVertical.TOP)
    street = instruction.maneuverPrimaryText
    gui_label(rl.Rectangle(rect.x + 2, rect.y + rect.height - 44, 320, 40), street, AR_STREET_PX, rl.Color(240, 244, 248, 255), FontWeight.BOLD,
              alignment_vertical=TextAlignmentVertical.TOP)
    if instruction.maneuverDistance < AR_ETA_HIDE:
      return
    label, val = _eta_values(instruction)[int(time.monotonic() / ETA_ROTATE) % 3]
    cx, cy = rect.x + rect.width, rect.y + rect.height
    rl.draw_circle_gradient(rl.Vector2(cx, cy), AR_ETA_VIGNETTE, rl.Color(4, 6, 8, 225), rl.BLANK)
    gui_label(rl.Rectangle(cx - 300, cy - AR_ETA_PX * FONT_SCALE - 4, 284, AR_ETA_PX * FONT_SCALE), val, AR_ETA_PX, rl.WHITE, FontWeight.BOLD,
              alignment=TextAlignment.RIGHT, alignment_vertical=TextAlignmentVertical.BOTTOM)
    gui_label(rl.Rectangle(cx - 300, cy - AR_ETA_PX * FONT_SCALE - 34, 284, 30), label, AR_ETA_LABEL_PX, rl.Color(215, 222, 230, 255), FontWeight.BOLD,
              alignment=TextAlignment.RIGHT, alignment_vertical=TextAlignmentVertical.BOTTOM)
