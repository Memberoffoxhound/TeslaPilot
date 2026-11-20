import pytest

from opendbc.car.chrysler.values import CUSW_CARS
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.car.subaru.values import SubaruFlags
from opendbc.car.volkswagen.values import VolkswagenFlags
from opendbc.sunnypilot.car.tesla.values import TeslaFlagsSP
from openpilot.selfdrive.ui import mads
from openpilot.selfdrive.ui.mads import MAIN_CRUISE, UNIFIED, STEERING_MODE, SCREEN_BUTTON

BUS = int(TeslaFlagsSP.HAS_VEHICLE_BUS)


ALL = {MAIN_CRUISE, UNIFIED, STEERING_MODE}
BRANDS = ["body", "byd", "chrysler", "ford", "gm", "honda", "hyundai", "mazda", "mg", "mock", "nissan", "psa", "rivian", "subaru", "tesla",
          "toyota", "volkswagen"]


@pytest.mark.parametrize("brand, flags, screen, car_flags, shown", [
  (None, 0, 0, 0, ALL),
  ("hyundai", 0, 0, int(HyundaiFlags.CANFD), ALL),
  ("volkswagen", 0, 0, int(VolkswagenFlags.MLB), {STEERING_MODE}),
  ("byd", 0, 0, 0, {STEERING_MODE}),
  ("subaru", 0, 0, int(SubaruFlags.PREGLOBAL), ALL),
  ("body", 0, 0, 0, set()),
  ("rivian", 0, 0, 0, set()),
  ("tesla", 0, 0, 0, set()),
  ("tesla", 0, 2, 0, set()),
  ("tesla", BUS, 0, 0, {SCREEN_BUTTON}),
  *[("tesla", BUS, s, 0, {SCREEN_BUTTON, UNIFIED}) for s in (1, 2, 3)],
])
def test_visible_options(brand, flags, screen, car_flags, shown):
  assert mads.visible_options(brand, flags, screen, car_flags) == shown


# Chrysler CUSW safety has no MADS main cruise or button, so only the brake mode applies
def test_chrysler_cusw():
  for fp in CUSW_CARS:
    assert mads.visible_options("chrysler", 0, 0, 0, fp) == {STEERING_MODE}


def test_every_brand():
  for brand in BRANDS:
    for flags, screen in ((0, 0), (BUS, 0), (BUS, 1)):
      shown = mads.visible_options(brand, flags, screen)
      assert shown <= ALL | {SCREEN_BUTTON}
      # brake is forced to disengage on Tesla, and the screen button is Tesla only
      if brand == "tesla":
        assert STEERING_MODE not in shown and MAIN_CRUISE not in shown
      else:
        assert SCREEN_BUTTON not in shown


def test_brand_list_is_complete():
  import os
  from opendbc.car import __file__ as car_init
  car_dir = os.path.dirname(car_init)
  ported = {d for d in os.listdir(car_dir) if os.path.isfile(os.path.join(car_dir, d, "interface.py"))}
  assert ported == set(BRANDS)


def test_welcome_copy():
  assert mads.MADS_TITLE == "MADS - Modular Assistive Driving System"
  assert mads.MADS_WELCOME[0] == mads.MADS_TITLE
  for card in mads.MADS_WELCOME:
    for text in (card if isinstance(card, tuple) else (card,)):
      assert "\u2014" not in text and "\u2013" not in text and "stands for" not in text


@pytest.mark.parametrize("brand", [None, "tesla", "toyota"])
def test_tesla_brake_copy(brand):
  cards, desc = mads.welcome_cards(brand), mads.toggle_description(brand)
  note = "On Tesla, pressing the brake cancels both steering and speed."
  assert cards[:len(mads.MADS_WELCOME)] == mads.MADS_WELCOME
  if brand == "tesla":
    assert cards[-2:] == ["Engage cruise again to get speed control back.", note]
    assert note in desc
  else:
    assert cards == mads.MADS_WELCOME and note not in desc
  for text in (desc, *[c for c in cards if isinstance(c, str)]):
    assert "\u2014" not in text and "\u2013" not in text
