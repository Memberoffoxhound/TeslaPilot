# Ported from sunnypilot, see LICENSE.sunnypilot.
from openpilot.common.params import Params
from opendbc.car import structs
from opendbc.sunnypilot.structs import CarParamsSP
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from opendbc.sunnypilot.car.hyundai.values import HyundaiFlagsSP, HyundaiSafetyFlagsSP
from opendbc.sunnypilot.car.tesla.values import MadsScreenButtonType, TeslaFlagsSP


MADS_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")


class MadsSteeringModeOnBrake:
  REMAIN_ACTIVE = 0
  PAUSE = 1
  DISENGAGE = 2


def get_mads_limited_brands(CP: structs.CarParams, CP_SP: CarParamsSP, params: Params) -> bool:
  if CP.brand == 'rivian':
    return True
  if CP.brand == 'tesla':
    if not CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS:
      return True
    screen_button = int(params.get("TeslaMadsScreenButton", return_default=True))
    return screen_button == MadsScreenButtonType.OFF

  return False


def read_steering_mode_param(CP: structs.CarParams, CP_SP: CarParamsSP, params: Params):
  if get_mads_limited_brands(CP, CP_SP, params):
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
  mads_partial_support = get_mads_limited_brands(CP, CP_SP, params)
  if mads_partial_support:
    params.put("MadsSteeringMode", 2, block=True)
    params.put_bool("MadsUnifiedEngagementMode", True, block=True)

  # no ACC MAIN button for these brands
  if CP.brand in MADS_NO_ACC_MAIN_BUTTON:
    params.remove("MadsMainCruiseAllowed")
