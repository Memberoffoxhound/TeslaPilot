import math
import time
import numpy as np
import raylib_nb as rl

from openpilot.selfdrive.navigation import ar_route as ar
from openpilot.selfdrive.navigation.helpers import latest_gps_source
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.polygon import draw_polygon

CARPET_HW = 1.1  # m
LINE_HW = 0.25  # m
CHEVRON_SPACING = 8.0  # m
CHEVRON_RANGE = (4.0, 200.0)  # m
MIN_X = 2.0  # m, nothing closer than this projects sanely
MIN_SPEED_FOR_BEARING = 2.0  # m/s
CHEV_BASE, CHEV_PEAK = 0.30, 0.95  # translucent at rest, flash at peak
CHEV_CYCLE, CHEV_STEP, CHEV_DECAY = 1.6, 0.055, 0.28  # s, the flash travels away from the car


class NavAROverlay:
  def __init__(self):
    self._route_ll = np.empty((0, 2))
    self._bearing = 0.0
    self._route = np.empty((0, 2))
    self._weight = np.empty(0)
    self.reason: str | None = 'route'

  def update(self, path_xyz: np.ndarray, calibrated: bool):
    sm = ui_state.sm
    if sm.updated['navRoute']:
      self._route_ll = np.array([(c.latitude, c.longitude) for c in sm['navRoute'].coordinates], dtype=np.float64).reshape((-1, 2))
    src = latest_gps_source(sm)
    gps = sm[src] if src else None
    nav = sm['navInstruction']
    self.reason = ar.fallback_reason(calibrated, gps.horizontalAccuracy if gps else None, sm['carState'].vEgo,
                                     nav.maneuverDistance, nav.maneuverModifier)
    if len(self._route_ll) < 2 or gps is None or len(path_xyz) < 2:
      self.reason = self.reason or 'route'
      return
    # gps bearing is noise when slow, so hold the last good one
    if gps.speed > MIN_SPEED_FOR_BEARING:
      self._bearing = gps.bearingDeg
    route = ar.resample(ar.ahead(ar.to_car(gps.latitude, gps.longitude, self._bearing, self._route_ll)), 1.0)
    path_xy = path_xyz[:, :2]
    max_x = min(120.0, max(25.0, nav.maneuverDistance - 15.0))
    route, _ = ar.heading_fix(route, path_xy, nav.maneuverDistance)
    route, _ = ar.fit_to_path(route, path_xy, max_x)
    route, weight = ar.blend_with_path(route, path_xy)
    keep = route[:, 0] > MIN_X
    self._route, self._weight = route[keep], weight[keep]
    self._path = path_xyz

  def render(self, rect: rl.Rectangle, transform: np.ndarray, height: float, color: tuple[int, int, int]):
    if self.reason is not None or len(self._route) < 2:
      return
    z = ar.ground_z(self._route, self._path, height)
    offset = np.array([rect.x, rect.y], dtype=np.float32)
    self._strip(rect, transform, z, CARPET_HW, rl.Color(*color, 110), offset)
    self._strip(rect, transform, z, LINE_HW, rl.Color(min(255, color[0] + 60), min(255, color[1] + 60), min(255, color[2] + 60), 230), offset)
    self._chevrons(rect, transform, height, offset)

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
    dt = (now - k * CHEV_STEP) % CHEV_CYCLE
    return dt / 0.06 if dt < 0.06 else math.exp(-(dt - 0.06) / CHEV_DECAY)

  def _chevrons(self, rect, transform, height, offset):
    r = self._route
    now = time.monotonic()
    cd = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(r, axis=0).T))))
    for k, s0 in enumerate(np.arange(CHEVRON_RANGE[0], min(CHEVRON_RANGE[1], cd[-1] - 3), CHEVRON_SPACING)):
      i, j = np.searchsorted(cd, s0), min(len(r) - 1, np.searchsorted(cd, s0 + 3.2))
      p, q = r[i], r[j]
      t = (q - p) / max(np.linalg.norm(q - p), 1e-6)
      n = np.array([-t[1], t[0]])
      fade = float(np.clip(1 - (s0 - CHEVRON_RANGE[0]) / (CHEVRON_RANGE[1] - CHEVRON_RANGE[0]), 0.4, 1))
      f = self._flash(k, now)
      # the glow is a wider copy of the chevron under it
      for hw, grow, a in ((1.0 + 0.9 * f, 0.5 * f, 0.35 * f * fade), (1.0, 0.0, (CHEV_BASE + (CHEV_PEAK - CHEV_BASE) * f) * fade)):
        if a < 0.02:
          continue
        m = n * hw
        poly = np.array([p + m, q + t * grow, p - m, p - m + t * (1.1 + grow), q + t * (1.1 + 2 * grow), p + m + t * (1.1 + grow)])
        pts, ok = self._project(transform, np.column_stack((poly, ar.ground_z(poly, self._path, height))))
        if ok.all():
          draw_polygon(rect, pts + offset, rl.Color(255, 255, 255, int(255 * a)))
