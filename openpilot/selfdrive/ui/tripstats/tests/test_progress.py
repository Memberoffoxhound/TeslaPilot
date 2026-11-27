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


def test_fade_alphas():
  assert p.fade_alphas(0) == (1.0, 0.0)
  assert p.fade_alphas(p.HOLD_S - p.FADE_S - 0.01)[0] == 1.0
  mid = p.fade_alphas(p.HOLD_S - p.FADE_S / 2)
  assert abs(mid[0] - 0.5) < 0.02 and abs(sum(mid) - 1) < 1e-9
  assert p.fade_alphas(p.HOLD_S + 0.01) == (0.0, 1.0)
  assert p.fade_alphas(2 * p.HOLD_S + 0.01)[0] == 1.0


def test_peek_offset():
  assert p.peek_offset(-0.1) == 0.0 and p.peek_offset(p.PEEK_S) == 0.0
  mid = p.peek_offset(p.PEEK_OUT_S)
  assert abs(mid - p.PEEK_PX) < 1e-6
  assert 0 < p.peek_offset(p.PEEK_OUT_S / 2) < p.PEEK_PX
  # springs back through a small overshoot, then settles
  assert p.peek_offset(p.PEEK_S - 0.01) < 2


def test_bar_colors_match_tripstats():
  from openpilot.selfdrive.ui.tripstats.recorder import COLORS, MANUAL, ENGAGED, OVERRIDE
  assert p.BAR_RGB[p.ENGAGED] == COLORS[ENGAGED]
  assert p.BAR_RGB[p.OVERRIDE] == COLORS[OVERRIDE]
  assert p.BAR_RGB[p.DISENGAGED] == COLORS[MANUAL]
