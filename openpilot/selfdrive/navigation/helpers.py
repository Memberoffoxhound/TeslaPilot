import time


def latest_gps_source(sm) -> str | None:
  """The service with the freshest usable GPS fix, or None."""
  now = time.monotonic()
  sources = [s for s in ('gpsLocation', 'gpsLocationExternal')
             if sm.valid[s] and sm[s].hasFix and 0 <= now - sm.recv_time[s] < 2]
  return max(sources, key=lambda s: sm.logMonoTime[s]) if sources else None


def route_active(sm) -> bool:
  # navd is publishing a live route: a valid instruction, or a route with points
  if sm.valid['navInstruction'] and sm.alive['navInstruction']:
    return True
  if sm.valid['navRoute']:
    return len(getattr(sm['navRoute'], 'coordinates', []) or []) >= 2
  return False


def nav_layout(route_on: bool, ar_view: bool = True, ar_ready: bool = False, alerting: bool = False) -> dict:
  # flags for the onroad widgets. no route: stock comma mici (ball, left DM, steering arc)
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
  show_ar = ar_view and ar_ready
  show_map = (not show_ar) and (not alerting)
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
