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


SLOT = textwrap.dedent('''
  S["custom"], S["size"] = True, 0
  OV = [0]
  def adv(sec, top=True, **kw):
    r = {}
    for i in range(max(1, round(sec * gui_app.target_fps))):
      r = frames(1, top=top, slot=True, **(kw if i == 0 else {}))
      OV[0] = max(OV[0], min(r.get("gpu", 0), r.get("pers", 0)))
    return {k: r.get(k, 0) for k in ("gpu", "pers")}
  out = {}
  adv(0.01, status=UIStatus.ENGAGED, chestnut_state=CS.ACTIVE, accel_progress=None)
  out["start_1"], out["start_2_8"], out["start_4"] = adv(1.0), adv(1.8), adv(1.2)
  adv(0.01, chestnut_state=CS.READY, accel_progress=("download", 0.1))
  out["dl_1"], out["dl_4"] = adv(1.0), adv(3.0)
  adv(0.01, accel_progress=("download", 0.3))
  out["peek_1"], out["peek_3"] = adv(1.0), adv(2.0)
  adv(0.01, accel_progress=("download", 0.4))
  out["same_step"] = adv(1.0)
  adv(0.01, accel_progress=("compile", None))
  adv(4.0)
  out["compile_29"], out["compile_31"], out["compile_33"] = adv(25.0), adv(2.0), adv(2.0)
  adv(0.01, chestnut_state=CS.FAILED, accel_progress=None)
  out["failed_3_5"], out["failed_4_6"] = adv(3.5), adv(1.1)
  adv(0.01, chestnut_state=CS.ACTIVE)
  adv(1.0)
  ss.personality = SimpleNamespace(raw=2)
  out["pers_change"] = adv(2 / gui_app.target_fps)
  out["pers_0_5"], out["pers_2"], out["resume_3_5"], out["resume_6"] = adv(0.5), adv(1.5), adv(1.5), adv(2.5)
  adv(0.01, top=False, chestnut_state=CS.READY, accel_progress=("download", 0.1))
  out["alert"] = adv(3.5, top=False)
  out["after_alert"] = adv(0.5)
  out["overlap"] = OV[0]
  S["size"] = 1
  out["large_dl_10"] = adv(10.0)
  print("RESULT" + json.dumps(out))
''')


@pytest.fixture(scope="module")
def slot(tmp_path_factory):
  return run_probe(tmp_path_factory, SLOT)


def up(r):
  return r["gpu"] > 200 and r["pers"] < 5


def down(r):
  return r["gpu"] < 5 and r["pers"] > 150


def test_shows_3s_at_drive_start_and_changes(slot):
  assert up(slot["start_1"]) and up(slot["start_2_8"]) and down(slot["start_4"])
  assert up(slot["dl_1"]) and down(slot["dl_4"])


def test_peeks_2s_per_25pct_download(slot):
  assert up(slot["peek_1"]) and down(slot["peek_3"]) and down(slot["same_step"])


def test_peeks_every_30s_compiling(slot):
  assert down(slot["compile_29"]) and up(slot["compile_31"]) and down(slot["compile_33"])


def test_failed_shows_4s(slot):
  assert up(slot["failed_3_5"]) and down(slot["failed_4_6"])


def test_personality_change_wins_then_show_resumes(slot):
  assert slot["pers_change"]["gpu"] < 5
  assert down(slot["pers_0_5"]) and down(slot["pers_2"])
  assert up(slot["resume_3_5"]) and down(slot["resume_6"])


def test_alerts_hide_both_and_skip_the_show(slot):
  assert slot["alert"] == {"gpu": 0, "pers": 0}
  assert down(slot["after_alert"])


def test_sequential_not_crossfade(slot):
  assert slot["overlap"] <= 6


def test_large_compass_keeps_progress_up(slot):
  assert slot["large_dl_10"]["gpu"] > 200


@pytest.fixture(scope="module")
def place(tmp_path_factory):
  return run_probe(tmp_path_factory, PLACE)


def _near(got, expect, tol=2):
  return abs(got[0] - expect[0]) <= tol and abs(got[1] - expect[1]) <= tol


def test_large_compass_bottom_right(place):
  assert _near(place["large"], [478, 195]) and _near(place["large_download"], [478, 195])
  assert _near(place["large_failed"], [466, 194])   # 60 wide, still 10 from the corner


def test_small_compass_on_the_personality(place):
  assert _near(place["small"], [470, 172])


def test_custom_off_stays_stock(place):
  assert _near(place["stock"], [86, 195]) and _near(place["stock_failed"], [86, 194])

ABSENT = textwrap.dedent('''
  out = {}
  for name, custom, size in (("large", True, 1), ("small", True, 0), ("stock", False, 1)):
    S["custom"], S["size"] = custom, size
    frames(30, UIStatus.ENGAGED, chestnut_state=CS.DISCONNECTED, accel_progress=("compile", None))
    out[name + "_compile"] = pos("gpu")
    frames(30, chestnut_state=CS.DISCONNECTED, accel_progress=("download", 0.4))
    out[name + "_download"] = pos("gpu")
  S["custom"], S["size"] = True, 0
  r = {}
  for _ in range(30):
    r = frames(1, top=True, slot=True, status=UIStatus.ENGAGED, chestnut_state=CS.DISCONNECTED,
               accel_progress=("compile", None))
  out["small_pers"] = r.get("pers", 0)
  print("RESULT" + json.dumps(out))
''')


@pytest.fixture(scope="module")
def absent(tmp_path_factory):
  return run_probe(tmp_path_factory, ABSENT)


def test_no_icon_when_disconnected_even_with_stale_progress(absent):
  for name in ("large_compile", "large_download", "small_compile", "small_download", "stock_compile", "stock_download"):
    assert absent[name] is None, name


def test_small_compass_keeps_the_personality_when_disconnected(absent):
  assert absent["small_pers"] > 150

