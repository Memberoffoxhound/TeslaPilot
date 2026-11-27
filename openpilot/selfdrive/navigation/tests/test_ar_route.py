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
