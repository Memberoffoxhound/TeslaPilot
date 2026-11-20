A_CRUISE_MIN = -1.2
A_CRUISE_MIN_SOFT = -0.5
BRAKING_FIRM_PARAM = "BrakingFirm"


def cruise_min_from_params(params) -> float:
  try:
    val = params.get(BRAKING_FIRM_PARAM, return_default=True)
  except (KeyError, OSError, TypeError, AttributeError):
    return A_CRUISE_MIN
  if val is None or val == "" or val == b"":
    firm = True
  elif isinstance(val, (bytes, bytearray)):
    firm = val not in (b"0", b"")
  elif isinstance(val, str):
    firm = val not in ("0", "")
  else:
    firm = bool(val)
  return A_CRUISE_MIN if firm else A_CRUISE_MIN_SOFT


def clamp_cruise_min(a_cruise_min: float) -> float:
  return max(a_cruise_min, A_CRUISE_MIN)


def braking_visible(has_longitudinal_control: bool) -> bool:
  return bool(has_longitudinal_control)
