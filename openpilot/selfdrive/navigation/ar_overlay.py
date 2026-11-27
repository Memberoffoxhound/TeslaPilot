import math
import time
import numpy as np

from openpilot.selfdrive.navigation import ar_route as ar
from openpilot.selfdrive.navigation.helpers import latest_gps_source

MIN_X = 2.0  # m, nothing closer than this projects sanely
MIN_SPEED_FOR_BEARING = 2.0  # m/s


def flat_fill_xs(cx: float, half: float, torque: float) -> tuple[float, float]:
  # fill from the center, positive torque to the right
  return (cx, cx + half * torque) if torque > 0 else (cx + half * torque, cx)


class NavAROverlay:
  # state and update for the AR route overlay; the mici widget adds render
  def __init__(self):
    self._route_ll = np.empty((0, 2))
    self._bearing = 0.0
    self._route = np.empty((0, 2))
    self._weight = np.empty(0)
    self._full = np.empty((0, 2))
    self._anchor: np.ndarray | None = None
    self._man_dist, self._man_mod = 1e9, ''
    self._path = np.empty((0, 3))
    self._z = np.empty(0)
    self._z_height: float | None = None
    self._reason_t = 0.0
    self.reason: str | None = 'route'

  def update(self, path_xyz: np.ndarray, calibrated: bool, sm=None, now: float | None = None, height: float | None = None):
    # sm is ui_state.sm on device; tests pass a stub so this stays headless
    if sm is None:
      from openpilot.selfdrive.ui.ui_state import ui_state
      sm = ui_state.sm
    # last published route, even if sm.updated already cleared it
    if sm.valid['navRoute']:
      self._route_ll = np.array([(c.latitude, c.longitude) for c in sm['navRoute'].coordinates], dtype=np.float64).reshape((-1, 2))
    src = latest_gps_source(sm)
    gps = sm[src] if src else None
    nav = sm['navInstruction']
    gps_ok = gps is not None and math.isfinite(float(gps.latitude)) and math.isfinite(float(gps.longitude))
    raw = ar.fallback_reason(calibrated, gps.horizontalAccuracy if gps else None, sm['carState'].vEgo,
                             nav.maneuverDistance, nav.maneuverModifier, holding=self.reason)
    now = time.monotonic() if now is None else now
    prev = self.reason
    self.reason, self._reason_t = ar.hold_fallback(self.reason, raw, self._reason_t, now)
    # missing route or GPS is applied after the hold, so a drop is not held as AR
    if self.reason is None and (len(self._route_ll) < 2 or not gps_ok or len(path_xyz) < 2):
      self.reason = 'gps' if gps is not None and not gps_ok else 'route'
    self._man_dist, self._man_mod = nav.maneuverDistance, nav.maneuverModifier
    if self.reason is not None:
      return
    need = sm.updated['modelV2'] or sm.updated['navRoute'] or (src is not None and sm.updated[src]) or prev is not None
    if not need:
      return
    if gps is None or len(self._route_ll) < 2 or len(path_xyz) < 2:
      self.reason = 'route'
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
    self._full = route
    keep = route[:, 0] > MIN_X
    self._route, self._weight = route[keep], weight[keep]
    self._path = path_xyz
    if height is not None:
      self._z = ar.ground_z(self._route, self._path, height)
      self._z_height = height
    else:
      self._z_height = None
