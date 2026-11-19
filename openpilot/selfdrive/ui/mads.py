# TITS (MADS) settings shown per car, rules ported from sunnypilot, see LICENSE.sunnypilot.
from opendbc.sunnypilot.car.tesla.values import MadsScreenButtonType, TeslaFlagsSP
from openpilot.sunnypilot.mads.helpers import MADS_NO_ACC_MAIN_BUTTON, mads_has_button, mads_main_reported

TITS_TITLE = "TITS - Trajectory Independent Torque Steering"
TITS_WELCOME: list = [
  ("TITS - Trajectory\nIndependent Torque Steering", "Tesla gave you ASS.\nTeslaPilot gives you TITS."),
  "TeslaPilot will continue steering when you cancel cruise while you handle speed.",
  "Engage cruise again to get speed control back.",
]
STEERING_MODES = ["remain active", "pause", "disengage"]
SCREEN_BUTTONS = ["off", "3 fingers", "4 fingers", "5 fingers"]

MAIN_CRUISE, UNIFIED, STEERING_MODE, SCREEN_BUTTON = "MadsMainCruiseAllowed", "MadsUnifiedEngagementMode", "MadsSteeringMode", "TeslaMadsScreenButton"


# limited brands are forced to disengage on brake with unified engagement
def limited(brand: str, flags: int, screen_button: int) -> bool:
  if brand == "rivian":
    return True
  if brand == "tesla":
    return not flags & TeslaFlagsSP.HAS_VEHICLE_BUS or screen_button == MadsScreenButtonType.OFF
  return False


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
  if not limited(brand, flags, screen_button):
    if main or mads_has_button(brand, car_flags, flags, screen_button, fingerprint):
      shown.add(UNIFIED)
    if brand != "tesla":
      shown.add(STEERING_MODE)
  if brand == "tesla" and flags & TeslaFlagsSP.HAS_VEHICLE_BUS:
    shown.add(SCREEN_BUTTON)
  return shown
