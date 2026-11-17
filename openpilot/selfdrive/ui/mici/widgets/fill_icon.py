import raylib_nb as rl

from openpilot.selfdrive.ui import accel_progress as ap
from openpilot.selfdrive.ui.mici.onroad import DIMMED_ICON_ALPHA
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget


def draw_fill(icon: rl.Texture, x: float, y: float, level: float, alpha: float = 1.0) -> None:
  # dimmed icon, bottom `level` solid white
  w, h = float(icon.width), float(icon.height)
  cut = float(round(h * (1.0 - level)))
  rl.draw_texture_ex(icon, rl.Vector2(x, y), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * DIMMED_ICON_ALPHA * alpha)))
  if cut < h:
    rl.draw_texture_pro(icon, rl.Rectangle(0, cut, w, h - cut), rl.Rectangle(x, y + cut, w, h - cut), rl.Vector2(0, 0), 0.0,
                        rl.Color(255, 255, 255, int(255 * alpha)))


def draw_progress(icon: rl.Texture, x: float, y: float, alpha: float = 1.0) -> bool:
  if (progress := ui_state.accel_progress) is None:
    return False
  kind, frac = progress
  if kind == 'download':
    draw_fill(icon, x, y, frac, alpha)
  else:  # compiling: no percent, flash like loading
    rl.draw_texture_ex(icon, rl.Vector2(x, y), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * ap.pulse(rl.get_time()) * alpha)))
  return True


class FillIcon(Widget):
  def __init__(self, icon: str, size: tuple[int, int]):
    super().__init__()
    self._icon = gui_app.texture(icon, *size)
    self.set_rect(rl.Rectangle(0, 0, float(size[0]), float(size[1])))
    self.set_enabled(False)

  def _render(self, _) -> None:
    draw_progress(self._icon, self._rect.x, self._rect.y + (self._rect.height - self._icon.height) / 2)
