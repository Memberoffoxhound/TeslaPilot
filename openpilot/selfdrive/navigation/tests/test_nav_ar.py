import time
from collections import defaultdict
from types import SimpleNamespace

import numpy as np

from openpilot.selfdrive.navigation.ar_overlay import NavAROverlay, flat_fill_xs
from openpilot.selfdrive.navigation.helpers import NavErrorGate, NavWidgetGuard, ROUTE_HOLD_S, RouteGate, nav_layout, route_active


class _SM:
  def __init__(self, msgs):
    self._msgs = msgs
    now = time.monotonic()
    self.valid = defaultdict(lambda: False, dict.fromkeys(msgs, True))
    self.updated = defaultdict(lambda: False)
    self.recv_time = defaultdict(lambda: now)
    self.logMonoTime = defaultdict(lambda: 1)
    self.alive = defaultdict(lambda: True)

  def __getitem__(self, key):
    return self._msgs[key]


def _sm(route=None, gps=None, v_ego=15.0, acc=3.0, inst_ok=True, route_ok=True):
  if route is None:
    coords = []
  else:
    coords = [SimpleNamespace(latitude=a, longitude=b) for a, b in route]
  if gps is None:
    gps = SimpleNamespace(latitude=38.9, longitude=-90.2, horizontalAccuracy=acc,
                          speed=10.0, bearingDeg=0.0, hasFix=True)
  msgs = {
    'navRoute': SimpleNamespace(coordinates=coords),
    'navInstruction': SimpleNamespace(maneuverDistance=200.0, maneuverModifier='right'),
    'carState': SimpleNamespace(vEgo=v_ego),
    'gpsLocation': gps,
  }
  sm = _SM(msgs)
  sm.valid['navInstruction'] = inst_ok
  sm.alive['navInstruction'] = inst_ok
  sm.valid['navRoute'] = route_ok
  sm.updated['navRoute'] = True
  sm.updated['modelV2'] = True
  sm.updated['gpsLocation'] = True
  return sm


def _path(n=10):
  return np.column_stack((np.linspace(0, 40, n), np.zeros(n), np.zeros(n)))


def test_overlay_update_headless_edge_cases():
  ov = NavAROverlay()
  path = np.empty((0, 3))
  sm = _sm(route=[], gps=SimpleNamespace(latitude=float('nan'), longitude=float('nan'),
                                         horizontalAccuracy=3.0, speed=10.0, bearingDeg=0.0, hasFix=True))
  ov.update(path, True, sm)
  assert ov.reason is not None

  ov = NavAROverlay()
  ov.update(np.empty((0, 3)), True, _sm(route=[]))
  assert ov.reason is not None

  ov = NavAROverlay()
  route = [(38.9, -90.2), (38.91, -90.2)]
  ov.update(np.empty((0, 3)), True, _sm(route=route))
  assert ov.reason is not None

  # NaN GPS with a short route and a short path still sets a reason and does not raise
  ov = NavAROverlay()
  gps = SimpleNamespace(latitude=float('nan'), longitude=float('nan'), horizontalAccuracy=3.0,
                        speed=10.0, bearingDeg=0.0, hasFix=True)
  ov.update(_path(), True, _sm(route=route, gps=gps))
  assert ov.reason is not None


def test_gps_lost_within_hold_does_not_crash():
  # AR active, then GPS drops 0.3 s after the view change: no AttributeError, reason set
  route = [(38.9, -90.2), (38.91, -90.2)]
  ov = NavAROverlay()
  ov.update(_path(), True, _sm(route=route), now=1000.0)
  assert ov.reason is None

  sm = _sm(route=route)
  sm.valid['gpsLocation'] = False
  ov.update(_path(), True, sm, now=1000.3)
  assert ov.reason is not None


def test_hysteresis_through_update():
  route = [(38.9, -90.2), (38.91, -90.2)]
  ov = NavAROverlay()
  # first frame switches at once (t_change 0 sentinel)
  ov.update(_path(), True, _sm(route=route, v_ego=15.0), now=1000.0)
  assert ov.reason is None

  # enter stopped below 1.0 m/s, but the 2 s hold keeps AR
  ov.update(_path(), True, _sm(route=route, v_ego=0.5), now=1000.5)
  assert ov.reason is None
  ov.update(_path(), True, _sm(route=route, v_ego=0.5), now=1002.1)
  assert ov.reason == 'stopped'

  # still stopped at 2.0 m/s (exit only above 3)
  ov.update(_path(), True, _sm(route=route, v_ego=2.0), now=1002.2)
  assert ov.reason == 'stopped'
  # raw is clear at 3.5, but the hold keeps 'stopped' for 2 s
  ov.update(_path(), True, _sm(route=route, v_ego=3.5), now=1002.3)
  assert ov.reason == 'stopped'
  ov.update(_path(), True, _sm(route=route, v_ego=3.5), now=1004.4)
  assert ov.reason is None

  # GPS enter above 10 m, exit only below 7 m
  ov.update(_path(), True, _sm(route=route, v_ego=15.0, acc=11.0), now=1004.5)
  assert ov.reason is None
  ov.update(_path(), True, _sm(route=route, v_ego=15.0, acc=11.0), now=1006.6)
  assert ov.reason == 'gps'
  ov.update(_path(), True, _sm(route=route, v_ego=15.0, acc=8.0), now=1006.7)
  assert ov.reason == 'gps'
  ov.update(_path(), True, _sm(route=route, v_ego=15.0, acc=6.0), now=1006.8)
  assert ov.reason == 'gps'
  ov.update(_path(), True, _sm(route=route, v_ego=15.0, acc=6.0), now=1008.9)
  assert ov.reason is None

  # calibrating bypasses the hold
  ov.update(_path(), False, _sm(route=route, v_ego=15.0), now=1009.0)
  assert ov.reason == 'calibrating'


def test_recompute_gating():
  route = [(38.9, -90.2), (38.91, -90.2)]
  ov = NavAROverlay()
  ov.update(_path(), True, _sm(route=route), now=1000.0)
  assert ov.reason is None
  first = ov._route.copy()
  sm = _sm(route=route)
  sm.updated['modelV2'] = False
  sm.updated['navRoute'] = False
  sm.updated['gpsLocation'] = False
  ov._bearing = 123.0
  ov.update(_path(), True, sm, now=1000.1)
  assert ov.reason is None
  assert ov._bearing == 123.0
  np.testing.assert_array_equal(ov._route, first)

  sm.updated['modelV2'] = True
  ov.update(_path(), True, sm, now=1000.2)
  assert ov._bearing != 123.0


def test_flat_bar_positive_fills_right():
  assert flat_fill_xs(100.0, 50.0, 1.0) == (100.0, 150.0)
  assert flat_fill_xs(100.0, 50.0, -0.5) == (75.0, 100.0)
  assert flat_fill_xs(100.0, 50.0, 0.0) == (100.0, 100.0)


def test_route_active_and_stock_layout():
  # no route: stock onroad flags, including dest-without-nav
  sm = _sm(route=[], inst_ok=False, route_ok=False)
  assert not route_active(sm)
  stock = nav_layout(False)
  assert stock == nav_layout(False, ar_view=True, alerting=True)
  assert not stock['show_ar'] and not stock['show_map'] and not stock['flat_bar']
  assert not stock['speed_right'] and not stock['dm_on_camera']
  assert not stock['show_trip'] and not stock['peek']
  assert stock['show_ball']

  # dest is irrelevant: a route with no live instruction or points is still stock
  sm = _sm(route=[], inst_ok=False, route_ok=True)
  assert not route_active(sm)

  # route starts: trip page and nav widgets may come up
  sm = _sm(route=[(38.9, -90.2), (38.91, -90.2)], inst_ok=True, route_ok=True)
  assert route_active(sm)
  on = nav_layout(True, ar_view=True)
  assert on['show_ar'] and on['flat_bar'] and on['speed_right'] and on['dm_on_camera']
  assert on['show_trip'] and not on['show_map'] and not on['show_ball']

  # route ends: back to stock
  sm.valid['navInstruction'] = False
  sm.alive['navInstruction'] = False
  sm._msgs['navRoute'] = SimpleNamespace(coordinates=[])
  sm.valid['navRoute'] = True
  assert not route_active(sm)
  assert nav_layout(False)['show_trip'] is False


def test_stale_nav_route_is_not_active():
  # navd stopped, leftover 300-point navRoute must not keep the nav UI on
  coords = [SimpleNamespace(latitude=38.9, longitude=-90.2 + i * 1e-4) for i in range(300)]
  sm = _sm(route=[], inst_ok=False, route_ok=True)
  sm._msgs['navRoute'] = SimpleNamespace(coordinates=coords)
  sm.valid['navRoute'] = True
  sm.alive['navRoute'] = True
  assert len(sm['navRoute'].coordinates) == 300
  assert not route_active(sm)
  assert not RouteGate().active(sm, now=1.0)


def test_route_gate_holds_after_drop():
  g = RouteGate()
  on = _sm(route=[(38.9, -90.2), (38.91, -90.2)], inst_ok=True)
  off = _sm(route=[(38.9, -90.2), (38.91, -90.2)], inst_ok=False)
  assert not g.active(off, now=1000.0)
  assert g.active(on, now=1000.0)
  assert g.active(off, now=1000.0 + ROUTE_HOLD_S - 0.1)
  assert not g.active(off, now=1000.0 + ROUTE_HOLD_S + 0.1)
  assert g.active(on, now=1010.0)


def test_overlay_reads_nav_route_without_updated_flag():
  # update() is skipped while the route gate is down, so the first on-route
  # frame often has sm.updated['navRoute'] already cleared; the last message must still load
  route = [(38.9, -90.2), (38.91, -90.2)]
  ov = NavAROverlay()
  sm = _sm(route=route)
  sm.updated['navRoute'] = False
  ov.update(_path(), True, sm, now=1000.0)
  assert ov.reason is None
  assert len(ov._route_ll) >= 2


def test_ar_view_does_not_open_stock_map_when_overlay_not_ready():
  # a live route in AR mode keeps the turn card and ETA; the carpet is separate
  pending = nav_layout(True, ar_view=True)
  assert pending['show_ar'] and not pending['show_map']
  assert pending['flat_bar'] and pending['speed_right'] and pending['dm_on_camera']
  assert pending['show_trip'] and not pending['show_ball']
  mapped = nav_layout(True, ar_view=False)
  assert not mapped['show_ar'] and mapped['show_map']
  hidden = nav_layout(True, ar_view=False, alerting=True)
  assert not hidden['show_map'] and not hidden['show_ar']


class _CountCoords:
  def __init__(self, inner):
    self.inner = inner
    self.reads = 0

  def __iter__(self):
    self.reads += 1
    return iter(self.inner)


def test_overlay_parses_nav_route_only_when_message_changes():
  # on-demand navRoute stays valid, so a validity check would reparse every frame
  route = [(38.9, -90.2), (38.91, -90.2)]
  coords = _CountCoords([SimpleNamespace(latitude=a, longitude=b) for a, b in route])
  ov = NavAROverlay()
  sm = _sm(route=route)
  sm._msgs['navRoute'] = SimpleNamespace(coordinates=coords)
  sm.valid['navRoute'] = True
  sm.updated['navRoute'] = False
  sm.logMonoTime['navRoute'] = 100
  for i in range(5):
    ov.update(_path(), True, sm, now=1000.0 + i)
  assert coords.reads == 1
  assert ov.reason is None
  sm.logMonoTime['navRoute'] = 200
  ov.update(_path(), True, sm, now=1006.0)
  assert coords.reads == 2


def test_bad_nav_route_does_not_raise():
  # a live route must still get HUD flags if the overlay cannot parse coordinates
  class Boom:
    def __iter__(self):
      raise TypeError('bad route')

  flags = nav_layout(True, ar_view=True)
  assert flags['show_ar'] and not flags['show_map']
  ov = NavAROverlay()
  sm = _sm(route=[(38.9, -90.2), (38.91, -90.2)])
  sm._msgs['navRoute'] = SimpleNamespace(coordinates=Boom())
  sm.logMonoTime['navRoute'] = 5
  ov.update(_path(), True, sm, now=1000.0)
  assert ov.reason is not None
  assert len(ov._route_ll) < 2


def _raise_value(msg):
  raise ValueError(msg)


def _raise_value_elsewhere(msg):
  raise ValueError(msg)


def _caught(fn, *args):
  try:
    fn(*args)
  except Exception as e:
    return e
  raise AssertionError('expected a raise')


def test_nav_error_gate_logs_identical_failures_once():
  g = NavErrorGate()
  a = _caught(_raise_value, 'boom')
  b = _caught(_raise_value, 'other')  # same type and site, different text
  assert g.record(a, now=1.0)
  assert not g.record(b, now=2.0)
  assert not g.record(_caught(_raise_value, 'boom'), now=10.9)
  assert g.record(_caught(_raise_value, 'boom'), now=11.1)
  assert g.record(_caught(_raise_value_elsewhere, 'boom'), now=11.2)


def test_nav_widget_guard_keeps_hud_errors_off_the_overlay():
  gate = NavErrorGate()
  overlay = NavWidgetGuard(gate)
  hud = NavWidgetGuard(gate)
  reason = type('W', (), {'reason': None})()

  def boom():
    raise RuntimeError('hud')

  assert hud.ready(now=1.0)
  err = _caught(boom)
  assert hud.trip(err, now=1.0)
  assert not hud.ready(now=5.9)
  assert hud.ready(now=6.1)
  assert reason.reason is None
  assert overlay.ready(now=5.9)

  def boom_ar():
    raise RuntimeError('ar')

  err = _caught(boom_ar)
  if overlay.trip(err, now=10.0):
    reason.reason = 'error'
  assert reason.reason == 'error'
  assert not overlay.ready(now=14.9)
  assert hud.ready(now=14.9)
