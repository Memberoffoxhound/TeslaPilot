"""Drive summary card and Home row: layout rules and hooks in the UI files. No raylib needed.
The recorder, store and card formatting are tested in selfdrive/ui/tripstats/tests."""
from pathlib import Path

UI = Path(__file__).resolve().parents[1]


def test_ui_hooks_present():
  main = (UI / "mici/layouts/main.py").read_text()
  assert "tripstats.tick(ui_state)" in main
  assert "draw_trip_row(" in (UI / "mici/layouts/home.py").read_text()


def test_home_row_day_label_fit(monkeypatch):
  """Home: "Day" label as big as the value with values at full size when it fits; both shrink together, never past avail."""
  import importlib
  import sys
  import types

  def measure(font, text, size):
    return types.SimpleNamespace(x=0.5 * size * len(text))

  monkeypatch.setitem(sys.modules, "openpilot.system.ui.lib.text_measure", types.SimpleNamespace(measure_text_cached=measure))
  monkeypatch.delitem(sys.modules, "openpilot.selfdrive.ui.mici.widgets.trip_row", raising=False)   # fresh import, dropped after
  tr = importlib.import_module("openpilot.selfdrive.ui.mici.widgets.trip_row")
  assert tr.HOME_LABEL == tr.BLOCK_VALUE == 34 and tr.ROW_GAP == 14 and tr.BLOCK_LABEL == 30
  for src in ("mici/layouts/home.py", "mici/widgets/drive_summary_card.py"):
    assert '("Day", ' in (UI / src).read_text() and '"Today ' not in (UI / src).read_text()
  monkeypatch.setattr(tr, "_draw_pair", lambda r, b, x, y, lbl, val, ls, vs: x + tr.measure_text_cached(0, lbl, ls).x + 10 +
                      tr.measure_text_cached(0, val, vs).x)
  row = (("Day", "52mi 24%"), ("Week", "330mi 64%"))
  need = sum(0.5 * 34 * (len(lbl) + len(val)) + 10 for lbl, val in row) + tr.ROW_GAP
  assert tr.draw_trip_row(None, None, 0, 0, need, *row) == (need, 34)
  w, vs = tr.draw_trip_row(None, None, 0, 0, need - 1, *row)
  assert vs == 33 and w <= need - 1
