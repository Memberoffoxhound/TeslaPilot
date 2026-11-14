import math

import raylib_nb as rl
from openpilot.cereal import messaging, log
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state


def restart_needed_callback(_=None):
  ui_state.params.put_bool("OnroadCycleRequested", True)


# 0/1 cycle params: LaneColor (1 tesla), CustomOnroadUi (1 custom), CompassSize (1 large)
LANE_COLOR_LABELS = ("openpilot", "tesla")
ONROAD_UI_LABELS = ("stock UI", "custom UI")
COMPASS_LARGE = 1
COMPASS_SIZE_LABELS = ("small", "large")

# Tesla Autopilot viz blue / stock openpilot green.
THEME_TESLA_RGB = (62, 140, 235)
THEME_OPENPILOT_RGB = (0, 255, 64)


def _mode(key: str, params: Params | None) -> int:
  return int((params or ui_state.params).get(key, return_default=True) == 1)


def lane_color_mode(params: Params | None = None) -> int:
  return _mode("LaneColor", params)


def lane_color_label(params: Params | None = None) -> str:
  return LANE_COLOR_LABELS[lane_color_mode(params)]


def next_lane_color(params: Params | None = None) -> int:
  return 1 - lane_color_mode(params)


def tesla_theme(params: Params | None = None) -> bool:
  return lane_color_mode(params) == 1


def theme_rgb(params: Params | None = None) -> tuple[int, int, int]:
  return THEME_TESLA_RGB if tesla_theme(params) else THEME_OPENPILOT_RGB


def theme_color(alpha: float = 1.0, params: Params | None = None) -> rl.Color:
  r, g, b = theme_rgb(params)
  a = int(max(0.0, min(1.0, float(alpha))) * 255)
  return rl.Color(r, g, b, a)


def onroad_ui_mode(params: Params | None = None) -> int:
  return _mode("CustomOnroadUi", params)


def onroad_ui_label(params: Params | None = None) -> str:
  return ONROAD_UI_LABELS[onroad_ui_mode(params)]


def next_onroad_ui(params: Params | None = None) -> int:
  return 1 - onroad_ui_mode(params)


def custom_onroad_ui(params: Params | None = None) -> bool:
  return onroad_ui_mode(params) == 1


def compass_size(params: Params | None = None) -> int:
  return _mode("CompassSize", params)


def compass_size_label(params: Params | None = None) -> str:
  return COMPASS_SIZE_LABELS[compass_size(params)]


def next_compass_size(params: Params | None = None) -> int:
  return 1 - compass_size(params)


CARDINALS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def heading_deg() -> float | None:
  sm = ui_state.sm
  if sm.recv_frame["gpsLocationExternal"] > 0 and sm["gpsLocationExternal"].hasFix:
    return sm["gpsLocationExternal"].bearingDeg % 360.0
  if sm.recv_frame["deviceMotion"] > 0 and sm["deviceMotion"].orientationNED.valid:
    return math.degrees(sm["deviceMotion"].orientationNED.z) % 360.0
  return None


def heading_letter() -> str | None:
  deg = heading_deg()
  if deg is None:
    return None
  return CARDINALS[int((deg + 22.5) % 360.0) // 45]


def _rpy_lines(roll: float, pitch: float, yaw: float) -> tuple[str, str, str]:
  # rpyCalib is device-frame Euler: roll, pitch, yaw.
  # Pitch/yaw words match stock. +roll is clockwise looking forward (right side down).
  pitch_s = f"P {abs(pitch):.1f}° {'down' if pitch > 0 else 'up'}"
  yaw_s = f"Y {abs(yaw):.1f}° {'left' if yaw > 0 else 'right'}"
  roll_s = f"R {abs(roll):.1f}° {'cw' if roll > 0 else 'ccw'}"
  return pitch_s, yaw_s, roll_s


def calib_button_value(params: Params | None = None, compact: bool = False) -> str:
  """Live roll/pitch/yaw for Reset Calibration. compact=True is three lines for C4."""
  params = params or Params()
  calib_bytes = params.get("CalibrationParams")
  if not calib_bytes:
    return "uncalibrated"

  try:
    calib = messaging.log_from_bytes(calib_bytes, log.Event).extrinsicsCalibration
    if calib.calStatus == log.ExtrinsicsCalibration.Status.uncalibrated:
      return "uncalibrated"
    roll = math.degrees(calib.rpyCalib[0])
    pitch = math.degrees(calib.rpyCalib[1])
    yaw = math.degrees(calib.rpyCalib[2])
  except Exception:
    cloudlog.exception("invalid CalibrationParams")
    return "uncalibrated"

  pitch_s, yaw_s, roll_s = _rpy_lines(roll, pitch, yaw)
  if compact:
    return f"{pitch_s}\n{yaw_s}\n{roll_s}"
  return f"{pitch_s}  {yaw_s}  {roll_s}"
