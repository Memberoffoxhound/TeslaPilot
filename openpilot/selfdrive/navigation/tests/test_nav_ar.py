import time
from collections import defaultdict
from types import SimpleNamespace

import numpy as np

from openpilot.selfdrive.navigation.ar_overlay import NavAROverlay


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


def _sm(route=None, gps=None, v_ego=15.0, acc=3.0):
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
  sm.updated['navRoute'] = True
  sm.updated['modelV2'] = True
  sm.updated['gpsLocation'] = True
  return sm


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
  path = np.column_stack((np.linspace(0, 40, 10), np.zeros(10), np.zeros(10)))
  ov.update(path, True, _sm(route=route, gps=gps))
  assert ov.reason is not None
