import math
import numpy as np

EARTH_R = 6378137.0
FIT_MAX_SHIFT = 16.0  # m, a bigger slide means the fit locked onto the wrong road
FIT_ITERS = 6
BLEND = (35.0, 65.0)  # m, the route rides the model path until here, then hands over to the map
AGREE = (1.5, 3.5)  # m, map and path are the same road inside this gap
GPS_POOR = 10.0  # m horizontal accuracy, enter the map
GPS_GOOD = 7.0  # m, return to AR only when this accurate
STOPPED = 1.0  # m/s, enter the map
MOVING = 3.0  # m/s, return to AR only above this
HOLD_S = 2.0  # s, keep the current view at least this long after a change
TIGHT_TURN = (-35.0, 18.0)  # m around a sharp maneuver: the camera cannot see the new road, then gps bearing lags
HEADING_FIX_MIN = 80.0  # m of straight model path needed to trust its heading
HEADING_FIX_MAX = 6.0  # deg
TIGHT = ('left', 'right', 'sharp left', 'sharp right', 'uturn')


def to_car(lat: float, lon: float, bearing_deg: float, route_ll: np.ndarray) -> np.ndarray:
  # route rows are (lat, lon); out is x forward, y right in m
  d_n = np.radians(route_ll[:, 0] - lat) * EARTH_R
  d_e = np.radians(route_ll[:, 1] - lon) * EARTH_R * math.cos(math.radians(lat))
  h = math.radians(bearing_deg)
  return np.column_stack((d_e * math.sin(h) + d_n * math.cos(h), d_e * math.cos(h) - d_n * math.sin(h)))


def resample(pts: np.ndarray, step: float = 2.0) -> np.ndarray:
  if len(pts) < 2:
    return pts
  cd = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))))
  s = np.arange(0.0, cd[-1], step)
  return np.column_stack((np.interp(s, cd, pts[:, 0]), np.interp(s, cd, pts[:, 1])))


def ahead(route_c: np.ndarray, back: float = 20.0, fwd: float = 900.0) -> np.ndarray:
  # the part of the route from just behind the car to fwd m along it
  if len(route_c) < 2:
    return route_c
  i = int(np.argmin(np.hypot(route_c[:, 0], route_c[:, 1])))
  cd = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(route_c, axis=0).T))))
  keep = (cd >= cd[i] - back) & (cd <= cd[i] + fwd)
  return route_c[keep]


def heading_fix(route_c: np.ndarray, path_xy: np.ndarray, maneuver_distance: float) -> tuple[np.ndarray, float]:
  # gps bearing lags after a turn; on a long straight model path, take the heading from the path
  span = min(float(path_xy[-1, 0]) if len(path_xy) else 0.0, maneuver_distance - 15.0)
  near = path_xy[path_xy[:, 0] < span]
  if span < HEADING_FIX_MIN or len(near) < 3 or np.abs(np.diff(near[:, 1], 2)).max() > 0.5:
    return route_c, 0.0
  m = (route_c[:, 0] > 10) & (route_c[:, 0] < span)
  if m.sum() < 10:
    return route_c, 0.0
  r = route_c[m, 1] - np.interp(route_c[m, 0], path_xy[:, 0], path_xy[:, 1])
  a = -math.atan(np.polyfit(route_c[m, 0], r, 1)[0])
  if abs(math.degrees(a)) > HEADING_FIX_MAX:
    return route_c, 0.0
  c, s = math.cos(a), math.sin(a)
  return np.column_stack((c * route_c[:, 0] - s * route_c[:, 1], s * route_c[:, 0] + c * route_c[:, 1])), math.degrees(a)


def fit_to_path(route_c: np.ndarray, path_xy: np.ndarray, max_x: float) -> tuple[np.ndarray, np.ndarray]:
  # slide the map route onto the model path, translation only
  m = (path_xy[:, 0] > 3) & (path_xy[:, 0] < max_x)
  shift = np.zeros(2)
  if m.sum() < 3 or len(route_c) < 2:
    return route_c, shift
  P = path_xy[m]
  # only segments that can match a path point are used (x < max_x + 20)
  cutoff = max_x + 20.0
  near = (route_c[:-1, 0] < cutoff) | (route_c[1:, 0] < cutoff)
  if not np.any(near):
    return route_c, shift
  A, B = route_c[:-1][near], route_c[1:][near]
  AB = B - A
  ab2 = np.maximum((AB * AB).sum(-1), 1e-9)
  for _ in range(FIT_ITERS):
    Q = P - shift
    t = np.clip(((Q[:, None, :] - A[None]) * AB[None]).sum(-1) / ab2[None], 0, 1)
    near = A[None] + AB[None] * t[..., None]
    k = np.linalg.norm(near - Q[:, None, :], axis=-1).argmin(1)
    shift = shift + (Q - near[np.arange(len(P)), k]).mean(0)
  if np.linalg.norm(shift) > FIT_MAX_SHIFT:
    return route_c, np.zeros(2)
  return route_c + shift, shift


def blend_with_path(route_c: np.ndarray, path_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
  # near the car the route sits on the model path, except where the map leaves it (an exit, a turn)
  if len(route_c) == 0 or len(path_xy) < 2:
    return route_c, np.ones(len(route_c))
  py = np.interp(route_c[:, 0], path_xy[:, 0], path_xy[:, 1])
  far = np.clip((route_c[:, 0] - BLEND[0]) / (BLEND[1] - BLEND[0]), 0, 1)
  agree = np.clip(1 - (np.abs(route_c[:, 1] - py) - AGREE[0]) / (AGREE[1] - AGREE[0]), 0, 1)
  on_path = route_c[:, 0] < path_xy[-1, 0]
  w = np.where(on_path, (1 - far) * agree, 0.0)
  out = route_c.copy()
  out[:, 1] = (1 - w) * route_c[:, 1] + w * py
  return out, np.maximum(far, 1 - agree)


def ground_z(pts: np.ndarray, path_xyz: np.ndarray, height: float) -> np.ndarray:
  # road height of the nearest model path point, so a turn does not take the height of the road ahead
  if len(path_xyz) == 0:
    return np.full(len(pts), height)
  d = np.linalg.norm(pts[:, None, :2] - path_xyz[None, :, :2], axis=-1)
  return height + path_xyz[d.argmin(1), 2]


def fallback_reason(calibrated: bool, gps_acc: float | None, v_ego: float, maneuver_distance: float, modifier: str,
                    holding: str | None = None) -> str | None:
  # why the overlay can't be trusted right now; the map view takes over
  # holding is the current reason, used for the wider exit thresholds
  if not calibrated:
    return 'calibrating'
  gps_lim = GPS_GOOD if holding == 'gps' else GPS_POOR
  if gps_acc is None or gps_acc > gps_lim:
    return 'gps'
  stop_lim = MOVING if holding == 'stopped' else STOPPED
  if v_ego < stop_lim:
    return 'stopped'
  if modifier in TIGHT and TIGHT_TURN[0] < maneuver_distance < TIGHT_TURN[1]:
    return 'turn'
  return None


def hold_fallback(prev: str | None, raw: str | None, t_change: float, now: float) -> tuple[str | None, float]:
  # keep the current view for HOLD_S after a change; calibrating applies at once
  if raw == prev:
    return prev, t_change
  if t_change == 0.0 or raw == 'calibrating' or now - t_change >= HOLD_S:
    return raw, now
  return prev, t_change
