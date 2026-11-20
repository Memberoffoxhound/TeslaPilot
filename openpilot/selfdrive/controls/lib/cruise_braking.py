from openpilot.common.params import UnknownKeyName

A_CRUISE_MIN = -1.2
A_CRUISE_MIN_SOFT = -0.5
BRAKING_FIRM_PARAM = "BrakingFirm"


def braking_firm_from_params(params, default=True, param=BRAKING_FIRM_PARAM) -> bool:
  try:
    val = params.get(param, return_default=True)
  except (KeyError, OSError, TypeError, AttributeError, UnknownKeyName):
    return default
  if val is None or val == "" or val == b"":
    return default
  if isinstance(val, (bytes, bytearray)):
    return val not in (b"0", b"")
  if isinstance(val, str):
    return val not in ("0", "")
  return bool(val)


def cruise_min_from_params(params) -> float:
  return A_CRUISE_MIN if braking_firm_from_params(params) else A_CRUISE_MIN_SOFT


def clamp_cruise_min(a_cruise_min: float) -> float:
  return max(a_cruise_min, A_CRUISE_MIN)


def braking_visible(has_longitudinal_control: bool) -> bool:
  return bool(has_longitudinal_control)


def braking_enabled(started: bool) -> bool:
  return not started
