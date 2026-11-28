# the nav arrive time is wall time in the trip stats zone, added in UTC and converted last
from datetime import UTC, datetime, timedelta

from openpilot.selfdrive.ui import tripstats as ts
from openpilot.selfdrive.ui.tripstats import tz
from openpilot.selfdrive.ui.tripstats.tests.test_store import Params


def chicago(tmp_path, monkeypatch):
  p = Params(tmp_path)
  p.d[tz.PARAM] = "America/Chicago"
  monkeypatch.setattr(ts, "_zone", (-1e9, None))
  return p


def utc(s: str) -> datetime:
  return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_arrive_in_the_gps_zone(tmp_path, monkeypatch):
  p = chicago(tmp_path, monkeypatch)
  t = ts.arrive_at(p, 1800, now=utc("2026-11-27T03:01:00"))  # 9:01 PM CST + 30 min
  assert (t.hour, t.minute, t.tzname()) == (21, 31, "CST")
  assert ts.clock_text(t) == "9:31"
  t = ts.arrive_at(p, 1800, now=utc("2026-07-01T14:00:00"))  # CDT
  assert (t.hour, t.tzname()) == (9, "CDT")


def test_arrive_across_the_fall_back(tmp_path, monkeypatch):
  p = chicago(tmp_path, monkeypatch)
  # 1:30 AM CDT Nov 1 plus an hour is 1:30 AM CST, not 2:30
  t = ts.arrive_at(p, 3600, now=utc("2026-11-01T06:30:00"))
  assert (t.hour, t.minute, t.tzname()) == (1, 30, "CST")


def test_arrive_across_the_spring_forward(tmp_path, monkeypatch):
  p = chicago(tmp_path, monkeypatch)
  # 1:30 AM CST Mar 8 plus an hour is 3:30 AM CDT, 2:30 does not exist
  t = ts.arrive_at(p, 3600, now=utc("2026-03-08T07:30:00"))
  assert (t.hour, t.minute, t.tzname()) == (3, 30, "CDT")


def test_arrive_is_hidden_while_the_clock_is_not_valid(tmp_path, monkeypatch):
  p = chicago(tmp_path, monkeypatch)
  monkeypatch.setattr(ts, "system_time_valid", lambda: False)
  assert ts.arrive_at(p, 600) is None
  monkeypatch.setattr(ts, "system_time_valid", lambda: True)
  t = ts.arrive_at(p, 600)
  assert abs(t.timestamp() - (datetime.now(UTC) + timedelta(seconds=600)).timestamp()) < 5


def test_arrive_without_a_saved_zone_uses_the_system_zone(tmp_path, monkeypatch):
  p = Params(tmp_path)
  monkeypatch.setattr(ts, "_zone", (-1e9, None))
  assert ts.arrive_at(p, 0, now=utc("2026-11-27T03:01:00")).tzinfo is not None
