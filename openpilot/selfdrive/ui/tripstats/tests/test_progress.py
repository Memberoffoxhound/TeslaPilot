from openpilot.selfdrive.ui.tripstats import progress as p


def test_classify():
  assert p.classify(True, "enabled", True) == p.ENGAGED
  assert p.classify(True, "overriding", True) == p.OVERRIDE
  assert p.classify(True, "preEnabled", False) == p.OVERRIDE
  assert p.classify(False, "disabled", True) == p.LAT_ONLY
  assert p.classify(False, "disabled", False) == p.DISENGAGED


def test_runs_merge_and_span():
  log = p.SegmentLog()
  for m, st in ((100, p.ENGAGED), (50, p.ENGAGED), (50, p.DISENGAGED), (0, p.OVERRIDE), (100, p.ENGAGED)):
    log.add(m, st)
  assert log.runs == [[150, p.ENGAGED], [50, p.DISENGAGED], [100, p.ENGAGED]]
  spans = log.spans(600)
  assert spans[0] == (0.0, 0.25, p.ENGAGED) and spans[-1][1] == 300 / 600


def test_runs_stay_bounded_and_keep_total():
  log = p.SegmentLog()
  for i in range(5000):
    log.add(1.0 + (i % 7), p.ENGAGED if i % 2 else p.DISENGAGED)
  assert len(log.runs) <= p.MAX_RUNS
  assert abs(sum(r[0] for r in log.runs) - log.total) < 1e-6
  assert log.runs[0][1] != log.runs[1][1]


def test_numbers():
  n = p.trip_numbers(4023.4, 2000.0, 754, 8046.7, False)
  assert n["remaining"] == ("5.0", "mi") and n["traveled"] == ("2.5", "mi")
  assert n["time"] == ("12:34", "min") and n["engaged"] == ("50", "%")
  assert abs(n["frac"] - 1 / 3) < 1e-3
  assert p.trip_numbers(100, 0, 3700, None, True)["frac"] is None
  assert p.fmt_time(3725) == ("1:02", "h")


def test_destination_name():
  assert p.destination_name({"latitude": 1, "longitude": 2, "place_name": " Home "}) == "Home"
  assert p.destination_name({"latitude": 1, "longitude": 2}) == p.UNKNOWN_DESTINATION
  assert p.destination_name(None) == p.UNKNOWN_DESTINATION
