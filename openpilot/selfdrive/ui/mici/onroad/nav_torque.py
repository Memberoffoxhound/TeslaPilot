import numpy as np
import raylib_nb as rl
from openpilot.selfdrive.ui.mici.onroad import blend_colors
from openpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from openpilot.selfdrive.ui.ui_state import UIStatus
from openpilot.system.ui.lib.polygon import draw_polygon, Gradient

# inset to clear the DM icon on the right; as thin as the nav progress bar
FLAT_LEFT, FLAT_RIGHT, FLAT_TOP, FLAT_HEIGHT = 20, 72, 2, 6


class FlatTorqueBar(TorqueBar):
  # same torque math, filters, colors and visibility as the stock mici arc; only the shape changes
  def _render(self, rect: rl.Rectangle) -> None:
    x = float(self._torque_filter.x)
    line_alpha = self._torque_line_alpha_filter.update(not self._hidden) * (1 - self._steer_status.weight(UIStatus.DISENGAGED))
    engaged = self._status.weight(UIStatus.ENGAGED)
    bar = rl.Rectangle(rect.x + FLAT_LEFT, rect.y + FLAT_TOP, rect.width - FLAT_LEFT - FLAT_RIGHT, FLAT_HEIGHT)
    cx, half = bar.x + bar.width / 2, bar.width / 2
    bg_alpha = 0.15 + (np.interp(abs(x), [0.5, 1.0], [0.25, 0.5]) - 0.15) * engaged
    rl.draw_rectangle_rounded(bar, 1.0, 6, rl.Color(255, 255, 255, int(255 * bg_alpha * line_alpha)))
    mix = max(0, abs(x) - 0.75) * 4
    start_color = blend_colors(rl.Color(255, 255, 255, int(255 * 0.9 * line_alpha)), rl.Color(255, 200, 0, int(255 * line_alpha)), mix)
    end_color = blend_colors(rl.Color(255, 255, 255, int(255 * 0.9 * line_alpha)), rl.Color(255, 115, 0, int(255 * line_alpha)), mix)
    dimmed = rl.Color(255, 255, 255, int(255 * 0.35 * line_alpha))
    start_color, end_color = blend_colors(dimmed, start_color, engaged), blend_colors(dimmed, end_color, engaged)
    if abs(x) > 0.004:
      # fill from the center, positive to the right; the gradient runs center to 65% of the bar half width
      x0, x1 = (cx, cx + half * x) if x > 0 else (cx + half * x, cx)
      pts = np.array([(x0, bar.y), (x1, bar.y), (x1, bar.y + bar.height), (x0, bar.y + bar.height)], dtype=np.float32)
      g0 = (cx - rect.x) / rect.width
      g1 = (cx + np.sign(x) * half * 0.65 - rect.x) / rect.width
      draw_polygon(rect, pts, gradient=Gradient(start=(g0, 0), end=(g1, 0), colors=[start_color, end_color], stops=[0.0, 1.0]))
    if abs(x) < 0.5:
      rl.draw_circle(int(cx), int(bar.y + bar.height / 2), 5, rl.Color(182, 182, 182, int(255 * 0.9 * line_alpha)))
