# Ported from sunnypilot, see LICENSE.sunnypilot.
from openpilot.common.params import Params
from opendbc.car import structs
from opendbc.sunnypilot.structs import CarParamsSP
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from opendbc.sunnypilot.car.hyundai.values import HyundaiFlagsSP, HyundaiSafetyFlagsSP
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.car.chrysler.values import CUSW_CARS
from opendbc.car.subaru.values import SubaruFlags
from opendbc.car.volkswagen.values import VolkswagenFlags
from opendbc.sunnypilot.car.tesla.values import MadsScreenButtonType, TeslaFlagsSP


MADS_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")
# panda safety tracks main cruise for these brands (VW MLB and Chrysler CUSW do not)
MADS_MAIN_REPORTED = ("chrysler", "ford", "gm", "honda", "hyundai", "mazda", "nissan", "subaru", "toyota", "volkswagen")
MADS_BUTTON_BRANDS = ("chrysler", "ford", "honda", "subaru")


# Chrysler CUSW safety has no MADS main cruise or button
def _chrysler_cusw(brand: str, fingerprint: str) -> bool:
  return brand == "chrysler" and fingerprint in CUSW_CARS


def mads_main_reported(brand: str, car_flags: int = 0, fingerprint: str = "") -> bool:
  return brand in MADS_MAIN_REPORTED and not (brand == "volkswagen" and car_flags & VolkswagenFlags.MLB) and \
    not _chrysler_cusw(brand, fingerprint)


# a MADS button panda safety reads (not on Subaru preglobal or Chrysler CUSW)
def mads_has_button(brand: str, car_flags: int = 0, sp_flags: int = 0, screen_button: int = 0, fingerprint: str = "") -> bool:
  if _chrysler_cusw(brand, fingerprint) or (brand == "subaru" and car_flags & SubaruFlags.PREGLOBAL):
    return False
  if brand == "hyundai":
    return bool(car_flags & (HyundaiFlags.HAS_LDA_BUTTON | HyundaiFlags.CANFD))
  if brand == "tesla":
    return bool(sp_flags & TeslaFlagsSP.HAS_VEHICLE_BUS) and screen_button != MadsScreenButtonType.OFF
  return brand in MADS_BUTTON_BRANDS


class MadsSteeringModeOnBrake:
  REMAIN_ACTIVE = 0
  PAUSE = 1
  DISENGAGE = 2


def get_mads_limited_brands(brand: str, flags: int, screen_button: int) -> bool:
  if brand == "rivian":
    return True
  if brand == "tesla":
    return not flags & TeslaFlagsSP.HAS_VEHICLE_BUS or screen_button == MadsScreenButtonType.OFF
  return False


def read_steering_mode_param(CP: structs.CarParams, CP_SP: CarParamsSP, params: Params):
  # Tesla: brake always ends steering too
  screen_button = int(params.get("TeslaMadsScreenButton", return_default=True) or 0)
  if CP.brand == "tesla" or get_mads_limited_brands(CP.brand, CP_SP.flags, screen_button):
    return MadsSteeringModeOnBrake.DISENGAGE

  return params.get("MadsSteeringMode", return_default=True)


def set_alternative_experience(CP: structs.CarParams, CP_SP: CarParamsSP, params: Params):
  enabled = params.get_bool("Mads")
  steering_mode = read_steering_mode_param(CP, CP_SP, params)

  if enabled:
    CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ENABLE_MADS

    if steering_mode == MadsSteeringModeOnBrake.DISENGAGE:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.MADS_DISENGAGE_LATERAL_ON_BRAKE
    elif steering_mode == MadsSteeringModeOnBrake.PAUSE:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.MADS_PAUSE_LATERAL_ON_BRAKE


def set_car_specific_params(CP: structs.CarParams, CP_SP: CarParamsSP, params: Params):
  if CP.brand == "hyundai":
    CP_SP.flags |= HyundaiFlagsSP.LONGITUDINAL_MAIN_CRUISE_TOGGLEABLE.value
    CP_SP.safetyParam |= HyundaiSafetyFlagsSP.LONG_MAIN_CRUISE_TOGGLEABLE

  # limited brands only support disengage on brake and unified engagement
  screen_button = int(params.get("TeslaMadsScreenButton", return_default=True) or 0)
  mads_partial_support = get_mads_limited_brands(CP.brand, CP_SP.flags, screen_button)
  if mads_partial_support:
    params.put("MadsSteeringMode", 2, block=True)
    params.put_bool("MadsUnifiedEngagementMode", True, block=True)
  elif CP.brand == "tesla":
    params.put("MadsSteeringMode", 2, block=True)

  # no ACC MAIN button for these brands, or panda does not see main cruise
  main_reported = mads_main_reported(CP.brand, CP.flags, CP.carFingerprint)
  if CP.brand in MADS_NO_ACC_MAIN_BUTTON or not main_reported:
    params.remove("MadsMainCruiseAllowed")

  # no main cruise and no button: engaging cruise is the only way in
  screen_button = int(params.get("TeslaMadsScreenButton", return_default=True) or 0)
  if not main_reported and not mads_has_button(CP.brand, CP.flags, CP_SP.flags, screen_button, CP.carFingerprint):
    params.put_bool("MadsUnifiedEngagementMode", True, block=True)
