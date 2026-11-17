# onroad gpu icon: bottom right with the large compass, shares the personality's slot with the small one
import textwrap

import pytest

from openpilot.selfdrive.ui.tests.test_onroad_fade import run_probe

PLACE = textwrap.dedent('''
  out = {}
  for name, custom, size, state in (("large", True, 1, CS.ACTIVE), ("large_failed", True, 1, CS.FAILED), ("small", True, 0, CS.ACTIVE),
                                    ("stock", False, 1, CS.ACTIVE), ("stock_failed", False, 1, CS.FAILED)):
    S["custom"], S["size"] = custom, size
    frames(30, UIStatus.ENGAGED, chestnut_state=state)
    out[name] = pos("gpu")
  S["custom"], S["size"] = True, 1
  frames(30, accel_progress=("download", 0.4))
  out["large_download"] = pos("gpu")
  print("RESULT" + json.dumps(out))
''')


@pytest.fixture(scope="module")
def place(tmp_path_factory):
  return run_probe(tmp_path_factory, PLACE)


def test_large_compass_bottom_right(place):
  assert place["large"] == [478, 195] and place["large_download"] == [478, 195]
  assert place["large_failed"] == [466, 194]   # 60 wide, still 10 from the corner


def test_small_compass_on_the_personality(place):
  assert place["small"] == [470, 172]


def test_custom_off_stays_stock(place):
  assert place["stock"] == [86, 195] and place["stock_failed"] == [86, 194]
