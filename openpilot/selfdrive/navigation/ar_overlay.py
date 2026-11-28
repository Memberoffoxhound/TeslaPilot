import math
import time
import numpy as np

from openpilot.selfdrive.navigation import ar_route as ar
from openpilot.selfdrive.navigation.helpers import latest_gps_source

MIN_X = 2.0  # m, nothing closer than this projects sanely
MIN_SPEED_FOR_BEARING = 2.0  # m/s
NAV_STALE_S = 2.5  # s, navd sends every second; older than this it is stuck (a blocked reroute)
PAST_TURN = 25.0  # m of the new road drawn past the turn
DRAW_S = (10.0, 120.0, 300.0)  # s of travel, min and max m of route drawn ahead
NO_TURN = ('arrive', 'depart')


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
    self._man_dist, self._man_mod, self._man_type = 1e9, '', ''
    self._nav_t = -1
    self._nav_seen = 0.0
    self._odo = 0.0
    self._odo_nav = 0.0
    self._last_now: float | None = None
    self._v = 0.0
    self._path = np.empty((0, 3))
    self._z = np.empty(0)
    self._z_height: float | None = None
    self._reason_t = 0.0
    self._route_t = -1
    self.reason: str | None = 'route'

  def update(self, path_xyz: np.ndarray, calibrated: bool, sm=None, now: float | None = None, height: float | None = None):
    # sm is ui_state.sm on device; tests pass a stub so this stays headless
    if sm is None:
      from openpilot.selfdrive.ui.ui_state import ui_state
      sm = ui_state.sm
    # parse only when the message itself changes, not on the one-frame updated flag
    if sm.logMonoTime['navRoute'] != self._route_t:
      self._route_t = sm.logMonoTime['navRoute']
      try:
        self._route_ll = np.array([(c.latitude, c.longitude) for c in sm['navRoute'].coordinates], dtype=np.float64).reshape((-1, 2))
      except (TypeError, ValueError, AttributeError):
        # empty route sets reason to 'route', which is visible, so this stays silent
        self._route_ll = np.empty((0, 2), dtype=np.float64)
    src = latest_gps_source(sm)
    gps = sm[src] if src else None
    nav = sm['navInstruction']
    now = time.monotonic() if now is None else now
    man_dist = self._live_distance(sm, nav, now)
    man_type = getattr(nav, 'maneuverType', '') or ''
    man_mod = '' if man_type in NO_TURN else nav.maneuverModifier
    gps_ok = gps is not None and math.isfinite(float(gps.latitude)) and math.isfinite(float(gps.longitude))
    raw = ar.fallback_reason(calibrated, gps.horizontalAccuracy if gps else None, sm['carState'].vEgo,
                             man_dist, man_mod, holding=self.reason)
    prev = self.reason
    self.reason, self._reason_t = ar.hold_fallback(self.reason, raw, self._reason_t, now)
    # missing route or GPS is applied after the hold, so a drop is not held as AR
    if self.reason is None and (len(self._route_ll) < 2 or not gps_ok or len(path_xyz) < 2):
      self.reason = 'gps' if gps is not None and not gps_ok else 'route'
    self._man_dist, self._man_mod, self._man_type = man_dist, man_mod, man_type
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
    # resample first: on a long straight the nearest vertex can be far ahead and crop away the road under the car
    route = ar.ahead(ar.resample(ar.to_car(gps.latitude, gps.longitude, self._bearing, self._route_ll), 1.0))
    path_xy = path_xyz[:, :2]
    max_x = min(120.0, max(25.0, man_dist - 15.0))
    route, _ = ar.heading_fix(route, path_xy, man_dist)
    route, _ = ar.fit_to_path(route, path_xy, max_x)
    route, weight = ar.blend_with_path(route, path_xy)
    self._full = route
    # draw only the road the driver can see: a few seconds ahead, and just past the next turn
    cd = ar.arc(route)
    cd = cd - cd[ar.car_index(route)] if len(route) else cd
    reach = float(min(DRAW_S[2], max(DRAW_S[1], DRAW_S[0] * self._v)))
    if self._man_mod not in ('', 'straight') and man_dist < reach:
      reach = max(man_dist, 0.0) + PAST_TURN
    keep = (route[:, 0] > MIN_X) & (cd <= reach)
    self._route, self._weight = route[keep], weight[keep]
    self._path = path_xyz
    if height is not None:
      self._z = ar.ground_z(self._route, self._path, height)
      self._z_height = height
    else:
      self._z_height = None

  def _live_distance(self, sm, nav, now: float) -> float:
    # navd sends once a second: carry the distance forward on the speedometer, drop it when stale
    v = max(0.0, float(sm['carState'].vEgo))
    if self._last_now is not None:
      self._odo += v * max(0.0, min(now - self._last_now, 0.5))
    self._last_now, self._v = now, v
    t = sm.logMonoTime['navInstruction']
    if t != self._nav_t:
      self._nav_t, self._nav_seen, self._odo_nav = t, now, self._odo
    if not sm.valid['navInstruction'] or now - self._nav_seen > NAV_STALE_S:
      return 1e9
    return float(nav.maneuverDistance) - (self._odo - self._odo_nav)
