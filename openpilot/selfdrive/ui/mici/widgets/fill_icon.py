import raylib_nb as rl

from openpilot.selfdrive.ui import accel_progress as ap
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget


def draw_fill(base: rl.Texture, fill: rl.Texture, x: float, y: float, level: float, pulse: float, alpha: float = 1.0) -> None:
  # bottom `level` of `fill` solid, the rest of `base` pulsing
  w, h = float(base.width), float(base.height)
  cut = float(round(h * (1.0 - level)))
  origin = rl.Vector2(0, 0)
  if cut > 0:
    rl.draw_texture_pro(base, rl.Rectangle(0, 0, w, cut), rl.Rectangle(x, y, w, cut), origin, 0.0,
                        rl.Color(255, 255, 255, int(255 * pulse * alpha)))
  if cut < h:
    rl.draw_texture_pro(fill, rl.Rectangle(0, cut, w, h - cut), rl.Rectangle(x, y + cut, w, h - cut), origin, 0.0,
                        rl.Color(255, 255, 255, int(255 * alpha)))


def draw_progress(base: rl.Texture, fill: rl.Texture, x: float, y: float, alpha: float = 1.0) -> bool:
  if (progress := ui_state.accel_progress) is None:
    return False
  t = rl.get_time()
  draw_fill(base, fill, x, y, ap.fill_level(progress, t), ap.pulse(t), alpha)
  return True


class FillIcon(Widget):
  def __init__(self, base: str, fill: str, size: tuple[int, int]):
    super().__init__()
    self._base = gui_app.texture(base, *size)
    self._fill = gui_app.texture(fill, *size)
    self.set_rect(rl.Rectangle(0, 0, float(size[0]), float(size[1])))
    self.set_enabled(False)

  def _render(self, _) -> None:
    draw_progress(self._base, self._fill, self._rect.x, self._rect.y + (self._rect.height - self._base.height) / 2)
