# TITS (MADS) settings shown per car, rules ported from sunnypilot, see LICENSE.sunnypilot.
from opendbc.sunnypilot.car.tesla.values import MadsScreenButtonType, TeslaFlagsSP
from openpilot.sunnypilot.mads.helpers import MADS_NO_ACC_MAIN_BUTTON, get_mads_limited_brands, mads_has_button, mads_main_reported

TITS_TITLE = "MADS - Modular Assistive Driving System"
TITS_WELCOME: list = [
  "MADS - Modular Assistive Driving System",
  "TeslaPilot will continue steering when you cancel cruise while you handle speed.",
  "Engage cruise again to get speed control back.",
]
TESLA_BRAKE = "On Tesla, pressing the brake cancels both steering and speed."


def welcome_cards(brand: str | None) -> list:
  return TITS_WELCOME + ([TESLA_BRAKE] if brand == "tesla" else [])


def toggle_description(brand: str | None) -> str:
  tesla = TESLA_BRAKE + "\n" if brand == "tesla" else ""
  return TITS_TITLE + "\nKeeps steering when you cancel cruise while you handle speed.\n" + tesla + "Change it while parked."


STEERING_MODES = ["remain active", "pause", "disengage"]
SCREEN_BUTTONS = ["off", "3 fingers", "4 fingers", "5 fingers"]

MAIN_CRUISE, UNIFIED, STEERING_MODE, SCREEN_BUTTON = "MadsMainCruiseAllowed", "MadsUnifiedEngagementMode", "MadsSteeringMode", "TeslaMadsScreenButton"


# no car seen yet: sunnypilot's defaults, everything but the brand page
# main cruise only where panda sees main; cruise engage only where main or a button can also engage;
# brake mode only where it is not forced (limited brands, Tesla); screen button only on Tesla with the vehicle bus
def visible_options(brand: str | None, flags: int = 0, screen_button: int = 0, car_flags: int = 0, fingerprint: str = "") -> set[str]:
  if not brand:
    return {MAIN_CRUISE, UNIFIED, STEERING_MODE}
  if brand == "body":
    return set()
  shown = set()
  main = mads_main_reported(brand, car_flags, fingerprint) and brand not in MADS_NO_ACC_MAIN_BUTTON
  if main:
    shown.add(MAIN_CRUISE)
  if not get_mads_limited_brands(brand, flags, screen_button):
    if main or mads_has_button(brand, car_flags, flags, screen_button, fingerprint):
      shown.add(UNIFIED)
    if brand != "tesla":
      shown.add(STEERING_MODE)
  if brand == "tesla" and flags & TeslaFlagsSP.HAS_VEHICLE_BUS:
    shown.add(SCREEN_BUTTON)
  return shown
