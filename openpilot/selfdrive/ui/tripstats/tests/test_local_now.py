# the nav arrive time is wall time in the trip stats zone, not the device's UTC clock
from datetime import timedelta

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import tz
from openpilot.selfdrive.ui.tripstats.tests.test_store import Params


def test_local_now_uses_the_gps_zone(tmp_path, monkeypatch):
  p = Params(tmp_path)
  p.d[tz.PARAM] = "America/Chicago"
  monkeypatch.setattr(ts, "_zone", (-1e9, None))
  now = ts.local_now(p)
  assert now.tzinfo is not None
  assert now.utcoffset() in (timedelta(hours=-6), timedelta(hours=-5))


def test_local_now_falls_back_to_the_system_zone(tmp_path, monkeypatch):
  p = Params(tmp_path)
  monkeypatch.setattr(ts, "_zone", (-1e9, None))
  assert ts.local_now(p).tzinfo is not None
