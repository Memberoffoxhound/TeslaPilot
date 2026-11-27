import time


def latest_gps_source(sm) -> str | None:
  """The service with the freshest usable GPS fix, or None."""
  now = time.monotonic()
  sources = [s for s in ('gpsLocation', 'gpsLocationExternal')
             if sm.valid[s] and sm[s].hasFix and 0 <= now - sm.recv_time[s] < 2]
  return max(sources, key=lambda s: sm.logMonoTime[s]) if sources else None


def route_active(sm) -> bool:
  # navd publishes a valid instruction every second while it has a route; stale in 10 s when navd stops
  return bool(sm.valid['navInstruction'] and sm.alive['navInstruction'])


ROUTE_HOLD_S = 8.0  # keep the nav layout up this long after the last live instruction


class RouteGate:
  # one shared gate so the road view and the trip page agree through a failed reroute
  def __init__(self, hold_s: float = ROUTE_HOLD_S):
    self.hold_s = hold_s
    self._last_t = 0.0

  def active(self, sm, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    if route_active(sm):
      self._last_t = now
      return True
    return self._last_t > 0.0 and now - self._last_t < self.hold_s


route_gate = RouteGate()


class NavErrorGate:
  # log a nav UI failure when the text changes, or again every interval_s
  def __init__(self, interval_s: float = 10.0):
    self.interval_s = interval_s
    self.msg = None
    self.t = 0.0

  def record(self, err: BaseException, now: float | None = None) -> bool:
    msg = f'{type(err).__name__}: {err}'
    now = time.monotonic() if now is None else now
    if msg != self.msg or now - self.t > self.interval_s:
      self.msg = msg
      self.t = now
      return True
    return False


def nav_layout(route_on: bool, ar_view: bool = True, alerting: bool = False) -> dict:
  # flags for the onroad widgets. no route: stock comma mici (ball, left DM, steering arc)
  # show_ar is the HUD and chrome; the carpet draws only when the overlay has no reason
  if not route_on:
    return {
      'show_ar': False,
      'show_map': False,
      'flat_bar': False,
      'speed_right': False,
      'show_ball': True,
      'dm_on_camera': False,
      'show_trip': False,
      'peek': False,
    }
  # AR mode keeps our HUD when the overlay is not ready; the stock map is NavView=map only
  show_ar = ar_view
  show_map = (not ar_view) and (not alerting)
  return {
    'show_ar': show_ar,
    'show_map': show_map,
    'flat_bar': show_ar,
    'speed_right': show_ar,
    'show_ball': not show_ar and not show_map,
    'dm_on_camera': show_ar,
    'show_trip': True,
    'peek': True,
  }
