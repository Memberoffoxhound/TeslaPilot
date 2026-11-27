import math
import time
import numpy as np
import raylib_nb as rl

from openpilot.selfdrive.navigation import ar_route as ar
from openpilot.selfdrive.navigation.ar_overlay import NavAROverlay as _NavAROverlay
from openpilot.system.ui.lib.polygon import draw_polygon

CARPET_HW = 1.1  # m
LINE_HW = 0.25  # m
CHEV_BASE, CHEV_PEAK = 0.30, 0.95  # translucent at rest, flash at peak
ARROW_STEP, ARROW_CYCLE, ARROW_DECAY = 0.13, 1.3, 0.3  # s, the flash travels in the turn direction
ARROW_ROWS, ARROW_W, ARROW_H, ARROW_C, ARROW_STEP_M, ARROW_LIFT = 5, 3.0, 3.2, 1.15, 1.6, 2.6  # m
ARROW_FADE_IN = 150.0  # m before the turn
ARROW_BLUE = (50, 150, 255)


class NavAROverlay(_NavAROverlay):

  def render(self, rect: rl.Rectangle, transform: np.ndarray, height: float, color: tuple[int, int, int]):
    if self.reason is not None or len(self._route) < 2:
      return
    z = ar.ground_z(self._route, self._path, height)
    offset = np.array([rect.x, rect.y], dtype=np.float32)
    self._strip(rect, transform, z, CARPET_HW, rl.Color(*color, 110), offset)
    self._strip(rect, transform, z, LINE_HW, rl.Color(min(255, color[0] + 60), min(255, color[1] + 60), min(255, color[2] + 60), 230), offset)
    self._arrow_row(rect, transform, height, offset)

  def _project(self, transform, pts3):
    p = transform @ pts3.T
    ok = p[2] > 1e-3
    return (p[:2] / np.where(ok, p[2], 1.0)).T, ok

  def _strip(self, rect, transform, z, hw, color, offset):
    # only the part past the hand-over: near the car comma's own path is the route
    d = np.gradient(self._route, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    n = np.column_stack((-d[:, 1], d[:, 0]))
    w = self._weight > 0.05
    if w.sum() < 2:
      return
    left = np.column_stack((self._route[w] - n[w] * hw, z[w]))
    right = np.column_stack((self._route[w] + n[w] * hw, z[w]))
    pl, okl = self._project(transform, left)
    pr, okr = self._project(transform, right)
    ok = okl & okr
    if ok.sum() < 2:
      return
    draw_polygon(rect, np.vstack((pl[ok], pr[ok][::-1])) + offset, color)

  def _flash(self, k: int, now: float) -> float:
    dt = (now - k * ARROW_STEP) % ARROW_CYCLE
    return dt / 0.06 if dt < 0.06 else math.exp(-(dt - 0.06) / ARROW_DECAY)

  def _arrow_anchor(self) -> np.ndarray | None:
    # just past the corner, on the outside of the turn, smoothed
    r = self._full
    if len(r) < 3 or self._man_dist < 25:
      return None
    cd = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(r, axis=0).T))))
    if self._man_dist > cd[-1]:
      return None
    mp = np.array([np.interp(self._man_dist, cd, r[:, 0]), np.interp(self._man_dist, cd, r[:, 1])])
    inc = np.array([np.interp(max(self._man_dist - 12, 0), cd, r[:, 0]), np.interp(max(self._man_dist - 12, 0), cd, r[:, 1])])
    tv = (mp - inc) / max(np.linalg.norm(mp - inc), 1e-6)
    rv = np.array([-tv[1], tv[0]])
    turn = -1.0 if 'left' in self._man_mod else 1.0
    anchor = mp + tv * 6.0 - turn * rv * 3.0
    self._anchor = anchor if self._anchor is None else 0.7 * self._anchor + 0.3 * anchor
    return self._anchor

  def _arrow_row(self, rect, transform, height, offset):
    # one upright row of overlapping chevrons facing the camera, hovering over the turn
    if self._man_mod in ('straight', '') or not (self._man_dist < ARROW_FADE_IN):
      self._anchor = None
      return
    anchor = self._arrow_anchor()
    if anchor is None or anchor[0] < 8:
      return
    fade = float(np.clip((ARROW_FADE_IN - self._man_dist) / 30, 0, 1) * np.clip((self._man_dist - 25) / 20, 0, 1))
    if fade < 0.02:
      return
    turn = -1.0 if 'left' in self._man_mod else 1.0
    los = anchor / max(np.linalg.norm(anchor), 1e-6)
    u = np.array([-los[1], los[0]])
    zg = float(ar.ground_z(anchor[None], self._path, height)[0])
    now = time.monotonic()
    total = ARROW_STEP_M * (ARROW_ROWS - 1) + ARROW_W
    shape = ((0, ARROW_H / 2), (ARROW_C, ARROW_H / 2), (ARROW_W, 0), (ARROW_C, -ARROW_H / 2), (0, -ARROW_H / 2), (ARROW_W - ARROW_C, 0))
    for k in range(ARROW_ROWS):
      f = self._flash(k, now)
      x0 = (-total / 2 + k * ARROW_STEP_M) * turn
      for grow, color, a in ((1.0 + 0.5 * f, ARROW_BLUE, 0.30 * f * fade), (1.0, (255, 255, 255), (CHEV_BASE + (CHEV_PEAK - CHEV_BASE) * f) * fade)):
        if a < 0.02:
          continue
        cx, cy = ARROW_W / 2, 0.0
        pts3 = np.array([[*(anchor + u * (x0 + turn * (cx + (px - cx) * grow))), zg - ARROW_LIFT - cy - (py - cy) * grow] for px, py in shape])
        pts, ok = self._project(transform, pts3)
        if ok.all():
          draw_polygon(rect, pts + offset, rl.Color(*color, int(255 * a)))
