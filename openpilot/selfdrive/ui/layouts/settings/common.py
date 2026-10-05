from __future__ import annotations

import subprocess
import sys
import time

import pyray as rl

from openpilot.common.basedir import BASEDIR
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


def theme_color(alpha: float = 1.0, params=None) -> rl.Color:
  a = int(max(0.0, min(1.0, float(alpha))) * 255)
  return rl.Color(0, 255, 64, a)


_trip_t = 0.0
_trip_flush = 0.0
_seed_started = False
_was_offroad = True


def _spawn_trip_job(kind: str) -> None:
  try:
    subprocess.Popen(
      [sys.executable, "-m", "openpilot.selfdrive.ui.layouts.settings.trip_seed", kind],
      cwd=BASEDIR,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      start_new_session=True,
    )
  except Exception:
    cloudlog.exception("trip job")


def spawn_trip_job(kind: str) -> None:
  _spawn_trip_job(kind)


def trip_snapshot() -> dict:
  from openpilot.selfdrive.ui.layouts.settings.trip_stats import stats_view
  return stats_view()


def tick_trip() -> None:
  """Live overlay = this drive only. Qlog cache owns completed miles."""
  global _trip_t, _trip_flush, _seed_started, _was_offroad
  now = time.monotonic()
  if not _seed_started:
    _seed_started = True
    _spawn_trip_job("seed")
  try:
    params = ui_state.params
    offroad = params.get_bool("IsOffroad")
    cs_ok = ui_state.sm.recv_frame["carState"] > 0
  except Exception:
    offroad, cs_ok = True, False
  park_cache = bool(offroad and not _was_offroad)
  _was_offroad = offroad

  if (not offroad) and cs_ok:
    dt = min(1.0, max(0.0, now - _trip_t)) if _trip_t else 0.0
    _trip_t = now
    v = max(0.0, float(ui_state.sm["carState"].vEgo))
    engaged = False
    try:
      engaged = ui_state.sm.recv_frame["selfdriveState"] > 0 and bool(ui_state.sm["selfdriveState"].enabled)
    except Exception:
      engaged = False
    route = params.get("CurrentRoute") or ""
    if isinstance(route, bytes):
      route = route.decode(errors="replace")
    d = v * dt if v > 0.15 else 0.0
    if d > 0:
      from openpilot.selfdrive.ui.layouts.settings.trip_stats import add_live
      add_live(d, d if engaged else 0.0, str(route), d if engaged else 0.0)
  else:
    _trip_t = now

  if now - _trip_flush > 1.0:
    _trip_flush = now
    try:
      from openpilot.selfdrive.ui.layouts.settings.trip_stats import flush_live
      flush_live()
    except Exception:
      cloudlog.exception("trip flush")

  if park_cache:
    try:
      from openpilot.selfdrive.ui.layouts.settings.trip_stats import flush_live
      flush_live()
    except Exception:
      cloudlog.exception("trip park flush")
    _spawn_trip_job("cache")
