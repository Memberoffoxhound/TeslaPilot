import numpy as np

from openpilot.selfdrive.navigation import ar_route as ar


def _straight(n=200, y=0.0):
  return np.column_stack((np.arange(-20, n, 2.0), np.full(len(np.arange(-20, n, 2.0)), y)))


def test_to_car_north():
  lat, lon = 38.945, -90.195
  pts = np.array([[lat + 100 / ar.EARTH_R * 180 / np.pi, lon]])
  c = ar.to_car(lat, lon, 0.0, pts)
  assert abs(c[0, 0] - 100) < 0.1 and abs(c[0, 1]) < 0.1
  c = ar.to_car(lat, lon, 90.0, pts)
  assert abs(c[0, 0]) < 0.1 and abs(c[0, 1] + 100) < 0.1


def test_fit_slides_onto_path():
  path = np.column_stack((np.arange(0, 100, 2.0), np.zeros(50)))
  fitted, shift = ar.fit_to_path(_straight(y=3.0), path, 80)
  assert abs(shift[1] + 3.0) < 0.05
  assert np.allclose(fitted[:, 1], 0, atol=0.05)


def test_fit_rejects_big_slide():
  path = np.column_stack((np.arange(0, 100, 2.0), np.zeros(50)))
  fitted, shift = ar.fit_to_path(_straight(y=40.0), path, 80)
  assert np.all(shift == 0) and np.allclose(fitted[:, 1], 40)


def test_heading_fix():
  path = np.column_stack((np.arange(0, 150, 2.0), np.zeros(75)))
  route = np.column_stack((np.arange(0, 300, 1.0), np.arange(0, 300, 1.0) * np.tan(np.radians(3))))
  fixed, deg = ar.heading_fix(route, path, 500)
  assert abs(deg + 3) < 0.05
  assert np.abs(fixed[(fixed[:, 0] > 10) & (fixed[:, 0] < 140), 1]).max() < 0.05
  _, deg = ar.heading_fix(route, path[:20], 500)
  assert deg == 0.0


def test_blend_keeps_exit():
  path = np.column_stack((np.arange(0, 100, 2.0), np.zeros(50)))
  route = _straight(y=0.5)
  out, w = ar.blend_with_path(route, path)
  near = (route[:, 0] > 2) & (route[:, 0] < 30)
  assert np.allclose(out[near, 1], 0, atol=1e-6)
  exit_ = route.copy()
  exit_[:, 1] = np.clip(exit_[:, 0] - 10, 0, None)
  out, _ = ar.blend_with_path(exit_, path)
  far = exit_[:, 0] > 20
  assert np.all(out[far, 1] > 5)


def test_fallback():
  assert ar.fallback_reason(False, 2.0, 20, 300, 'right') == 'calibrating'
  assert ar.fallback_reason(True, 15.0, 20, 300, 'right') == 'gps'
  assert ar.fallback_reason(True, 2.0, 0.2, 300, 'right') == 'stopped'
  assert ar.fallback_reason(True, 2.0, 8, 5, 'right') == 'turn'
  assert ar.fallback_reason(True, 2.0, 8, 5, 'slight right') is None
  assert ar.fallback_reason(True, 2.0, 20, 300, 'right') is None


def test_fallback_hysteresis():
  assert ar.fallback_reason(True, 9.0, 20, 300, 'right') is None
  assert ar.fallback_reason(True, 11.0, 20, 300, 'right') == 'gps'
  assert ar.fallback_reason(True, 8.0, 20, 300, 'right', holding='gps') == 'gps'
  assert ar.fallback_reason(True, 6.0, 20, 300, 'right', holding='gps') is None
  assert ar.fallback_reason(True, 2.0, 0.5, 300, 'right') == 'stopped'
  assert ar.fallback_reason(True, 2.0, 2.0, 300, 'right', holding='stopped') == 'stopped'
  assert ar.fallback_reason(True, 2.0, 3.5, 300, 'right', holding='stopped') is None
  t0 = 100.0
  reason, ts = ar.hold_fallback(None, 'stopped', 0.0, t0)
  assert reason == 'stopped' and ts == t0
  reason, ts = ar.hold_fallback('stopped', None, t0, t0 + 0.5)
  assert reason == 'stopped' and ts == t0
  reason, ts = ar.hold_fallback('stopped', None, t0, t0 + 2.1)
  assert reason is None and ts == t0 + 2.1
  reason, ts = ar.hold_fallback(None, 'calibrating', t0, t0 + 0.1)
  assert reason == 'calibrating'


def test_ahead_keeps_the_road_under_the_car_on_a_long_segment():
  # route 00000211: a 113 m straight, the nearest vertex was 44 m ahead and the road under the car was cut off
  route = np.array([[-69.0, -1.3], [44.0, -2.3], [84.0, -2.1], [85.0, 26.0]])
  old = ar.ahead(route)
  assert old[0, 0] > 40
  new = ar.ahead(ar.resample(route, 1.0))
  assert -21 < new[0, 0] < -18


def test_car_index_takes_the_leg_facing_forward():
  # out and back on one road: the leg behind runs backward, the one under the car forward
  back = np.column_stack((np.linspace(50, -50, 101), np.full(101, 0.5)))
  fwd = np.column_stack((np.linspace(-50, 50, 101), np.zeros(101)))
  route = np.vstack((back, fwd))
  i = ar.car_index(route)
  assert i > 101 and abs(route[i, 0]) < 1.5


def test_turn_deg_sign():
  right = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 20.0]])
  left = right * np.array([1.0, -1.0])
  assert ar.turn_deg(right, ar.arc(right), 20.0) > 80
  assert ar.turn_deg(left, ar.arc(left), 20.0) < -80
  straight = np.array([[0.0, 0.0], [40.0, 0.0]])
  assert abs(ar.turn_deg(straight, ar.arc(straight), 20.0)) < 1


def test_no_arrows_on_a_straight_road():
  # route 00000211: navd said right turn at 42 m on a straight road and the chevrons floated beside it
  straight = ar.resample(np.array([[0.0, 0.0], [300.0, 0.0]]), 1.0)
  cd = ar.arc(straight)
  assert not ar.bends(straight, cd, 42.0, 1.0)
  corner = ar.resample(np.array([[0.0, 0.0], [60.0, 0.0], [60.0, 60.0]]), 1.0)
  cd = ar.arc(corner)
  assert ar.bends(corner, cd, 60.0, 1.0)
  assert not ar.bends(corner, cd, 60.0, -1.0)  # wrong way
  gentle = ar.resample(np.array([[0.0, 0.0], [60.0, 0.0], [120.0, 12.0]]), 1.0)  # about 11 degrees
  assert not ar.bends(gentle, ar.arc(gentle), 60.0, 1.0)
