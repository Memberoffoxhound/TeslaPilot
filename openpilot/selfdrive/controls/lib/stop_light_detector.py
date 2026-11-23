import math
import time
import numpy as np

from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants

CRUISING_SPEED = 5.0
STOP_DISTANCE = 6.0
PLANNER_TIME = ModelConstants.T_IDXS[-1]
MODEL_TIME_NO_CEM = PLANNER_TIME - 2.0
THRESHOLD = 1.0 - 1.0 / math.e
RADARLESS_TRACK_HOLD_TIME = 0.45

FILTER_TIME_LIGHTS = [0.9, 0.8, 0.75, 0.55]
LIGHT_BOOSTS = [1.0, 1.2, 1.1, 1.0]
LIGHT_MAX_TIME = 9.0
LOW_SPEED_LIGHT_FILTER_TIME = 0.35
LEAD_CLEAR_FILTER_TIME_LOW = 0.6
LEAD_CLEAR_FILTER_TIME_HIGH = 0.35
STOP_LIGHT_ON_MARGIN = 2.5
STOP_LIGHT_OFF_MARGIN = 4.0
STOP_LIGHT_MODEL_HOLD_STRONG_MARGIN = 10.0
STOP_LIGHT_LEAD_BLOCK_MARGIN = 15.0
STOP_LIGHT_MODEL_BRAKE_MIN = 0.5
STOP_LIGHT_MODEL_LEAD_MARGIN = 3.0
STOP_LIGHT_HANDOFF_MAX_LEAD_SPEED = 2.0
STOP_LIGHT_DETECTED_HOLD_TIME = 4.0
STOP_APPROACH_LATCH_TIME = 1.0
STOP_APPROACH_MAX_LEAD_SPEED = 4.5
STOP_APPROACH_MIN_MODEL_PROB = 0.9
TURN_STOP_LIGHT_VETO_MAX_SPEED = 15.0 * CV.MPH_TO_MS
TURN_STOP_LIGHT_VETO_STEERING_ANGLE = 45.0

VISION_LEAD_TRACK_MIN_DISTANCE = 25.0
VISION_LEAD_TRACK_BASE_TIME_GAP = 1.75
VISION_LEAD_TRACK_CLOSING_GAIN = 0.20
VISION_LEAD_TRACK_CLOSING_CAP = 2.50
VISION_LEAD_TRACK_EXIT_TIME_GAP = 2.30
VISION_LEAD_TRACK_EXIT_MAX_LATERAL_OFFSET = 1.6
VISION_LEAD_TRACK_EXIT_MIN_MODEL_PROB = 0.70
VISION_LEAD_TRACK_CONTINUITY_MIN_MODEL_PROB = 0.95
VISION_LEAD_TRACK_CONTINUITY_MAX_LATERAL_OFFSET = 1.1
VISION_LEAD_TRACK_CONTINUITY_TIME_GAP_GAIN = 0.55
VISION_LEAD_TRACK_CONTINUITY_FULL_SPEED = 20.0
VISION_LEAD_TRACK_CONTINUITY_FADE_SPEED = 25.0
RADARLESS_MATCHED_FOLLOW_MIN_SPEED = 22.0
RADARLESS_MATCHED_FOLLOW_MAX_REL_SPEED = 2.0
RADARLESS_MATCHED_FOLLOW_MIN_HEADWAY = 0.95
RADARLESS_MATCHED_FOLLOW_HEADWAY_BELOW_TARGET = 0.35
RADARLESS_MATCHED_FOLLOW_HEADWAY_ABOVE_TARGET = 0.90
RADARLESS_MATCHED_FOLLOW_MAX_LEAD_BRAKE = 0.35
RADARLESS_MATCHED_FOLLOW_MIN_MODEL_PROB = 0.70
DEFAULT_T_FOLLOW = 1.45


def _interp(x: float, xp: list[float], fp: list[float]) -> float:
  return float(np.interp(x, xp, fp))


def _smoothstep(value: float, start: float, end: float) -> float:
  factor = min(1.0, max(0.0, (float(value) - float(start)) / max(float(end) - float(start), 1e-3)))
  return factor * factor * (3.0 - 2.0 * factor)


def should_track_lead(lead_status: bool, lead_distance: float, model_length: float, stop_distance: float,
                      v_ego: float, *, v_lead: float | None = None, radar: bool = False) -> bool:
  if not lead_status:
    return False
  tracking_buffer = max(float(stop_distance), 4.0)
  model_limit = float(model_length) + tracking_buffer
  if radar:
    return float(lead_distance) < model_limit
  closing_speed = max(0.0, float(v_ego) - float(v_lead if v_lead is not None else v_ego))
  vision_time_gap = VISION_LEAD_TRACK_BASE_TIME_GAP + min(closing_speed * VISION_LEAD_TRACK_CLOSING_GAIN,
                                                          VISION_LEAD_TRACK_CLOSING_CAP)
  vision_limit = max(VISION_LEAD_TRACK_MIN_DISTANCE, float(v_ego) * vision_time_gap + tracking_buffer)
  return float(lead_distance) < min(model_limit, vision_limit)


def should_hold_tracked_vision_lead(lead_status: bool, lead_distance: float, model_length: float, stop_distance: float,
                                    v_ego: float, *, model_prob: float,
                                    y_rel: float, path_y: float = 0.0, radar: bool = False) -> bool:
  if not lead_status or radar or float(model_prob) < VISION_LEAD_TRACK_EXIT_MIN_MODEL_PROB:
    return False
  if abs(float(y_rel) + float(path_y)) > VISION_LEAD_TRACK_EXIT_MAX_LATERAL_OFFSET:
    return False
  tracking_buffer = max(float(stop_distance), 4.0)
  model_limit = float(model_length) + tracking_buffer
  vision_exit_limit = max(VISION_LEAD_TRACK_MIN_DISTANCE,
                          float(v_ego) * VISION_LEAD_TRACK_EXIT_TIME_GAP + tracking_buffer)
  if float(lead_distance) < min(model_limit, vision_exit_limit):
    return True
  path_relative_offset = abs(float(y_rel) + float(path_y))
  if (float(model_prob) < VISION_LEAD_TRACK_CONTINUITY_MIN_MODEL_PROB or
      path_relative_offset > VISION_LEAD_TRACK_CONTINUITY_MAX_LATERAL_OFFSET):
    return False
  speed_factor = 1.0 - _smoothstep(
    v_ego,
    VISION_LEAD_TRACK_CONTINUITY_FULL_SPEED,
    VISION_LEAD_TRACK_CONTINUITY_FADE_SPEED,
  )
  continuity_time_gap = VISION_LEAD_TRACK_EXIT_TIME_GAP + VISION_LEAD_TRACK_CONTINUITY_TIME_GAP_GAIN * speed_factor
  continuity_exit_limit = max(VISION_LEAD_TRACK_MIN_DISTANCE,
                              float(v_ego) * continuity_time_gap + tracking_buffer)
  return float(lead_distance) < continuity_exit_limit


def is_radarless_matched_follow_window(v_ego: float, lead_distance: float, v_lead: float, t_follow: float, *,
                                       radar: bool = False, lead_brake: float = 0.0,
                                       lead_prob: float = 0.0,
                                       min_speed: float = RADARLESS_MATCHED_FOLLOW_MIN_SPEED) -> bool:
  if radar or float(t_follow) <= 0.0 or float(v_ego) < float(min_speed):
    return False
  if float(lead_prob) < RADARLESS_MATCHED_FOLLOW_MIN_MODEL_PROB:
    return False
  if float(lead_brake) > RADARLESS_MATCHED_FOLLOW_MAX_LEAD_BRAKE:
    return False
  relative_speed = float(v_ego) - float(v_lead)
  if abs(relative_speed) > RADARLESS_MATCHED_FOLLOW_MAX_REL_SPEED:
    return False
  actual_headway = float(lead_distance) / max(float(v_ego), 1e-3)
  min_headway = max(RADARLESS_MATCHED_FOLLOW_MIN_HEADWAY,
                    float(t_follow) - RADARLESS_MATCHED_FOLLOW_HEADWAY_BELOW_TARGET)
  max_headway = float(t_follow) + RADARLESS_MATCHED_FOLLOW_HEADWAY_ABOVE_TARGET
  return min_headway <= actual_headway <= max_headway


def calculate_road_curvature(model_v2, v_ego: float) -> float:
  try:
    orientation_rate = np.array(model_v2.orientationRate.z)
    velocity = np.array(model_v2.velocity.x)
    if len(orientation_rate) == 0 or len(orientation_rate) != len(velocity):
      return 0.0
    lateral_acceleration = orientation_rate * velocity
    index = int(np.argmax(np.abs(lateral_acceleration)))
    predicted_lateral_acc = float(lateral_acceleration[index])
    return float(predicted_lateral_acc / max(v_ego, 1.0) ** 2)
  except (AttributeError, TypeError, ValueError):
    return 0.0


class StopLightDetector:
  def __init__(self):
    self.stop_light_filter = FirstOrderFilter(0.0, FILTER_TIME_LIGHTS[1], DT_MDL)
    self.lead_clear_filter = FirstOrderFilter(0.0, LEAD_CLEAR_FILTER_TIME_LOW, DT_MDL)
    self.tracking_lead_filter = FirstOrderFilter(0.0, 1.0, DT_MDL)
    self.tracking_lead = False
    self.radarless_follow_hold_until = 0.0
    self.stop_light_detected = False
    self.stop_light_model_detected = False
    self.stop_light_detected_hold_until = 0.0
    self.stop_approach_hold_until = 0.0

  def reset(self) -> None:
    self.stop_light_filter.x = 0.0
    self.stop_light_detected = False
    self.stop_light_model_detected = False
    self.stop_light_detected_hold_until = 0.0
    self.lead_clear_filter.x = 0.0
    self.stop_approach_hold_until = 0.0

  def _update_lead_status(self, v_ego: float, model_length: float, model_v2, lead_one, now: float) -> bool:
    if lead_one is None or not bool(getattr(lead_one, "status", False)):
      self.radarless_follow_hold_until = 0.0
      self.tracking_lead_filter.update(False)
      return self.tracking_lead_filter.x >= THRESHOLD

    d_rel = float(getattr(lead_one, "dRel", float("inf")))
    v_lead = float(getattr(lead_one, "vLead", float("inf")))
    radar = bool(getattr(lead_one, "radar", False))
    model_prob = float(getattr(lead_one, "modelProb", 0.0))
    y_rel = float(getattr(lead_one, "yRel", 0.0))
    a_lead_k = float(getattr(lead_one, "aLeadK", 0.0))

    pos = getattr(model_v2, "position", None)
    pos_x = getattr(pos, "x", []) if pos is not None else []
    pos_y = getattr(pos, "y", []) if pos is not None else []
    lead_path_y = float(np.interp(d_rel, pos_x, pos_y)) if len(pos_x) > 0 and len(pos_y) == len(pos_x) else 0.0

    following_lead = should_track_lead(
      True, d_rel, model_length, STOP_DISTANCE, v_ego, v_lead=v_lead, radar=radar,
    )
    continuity_candidate = self.tracking_lead or self.tracking_lead_filter.x >= THRESHOLD * 0.6
    if not following_lead and continuity_candidate:
      following_lead = should_hold_tracked_vision_lead(
        True, d_rel, model_length, STOP_DISTANCE, v_ego,
        model_prob=model_prob, y_rel=y_rel, path_y=lead_path_y, radar=radar,
      )

    matched_follow = is_radarless_matched_follow_window(
      v_ego, d_rel, v_lead, DEFAULT_T_FOLLOW,
      radar=radar, lead_brake=max(0.0, -a_lead_k), lead_prob=model_prob,
    )
    if matched_follow and (following_lead or self.tracking_lead or self.tracking_lead_filter.x >= THRESHOLD * 0.6):
      self.radarless_follow_hold_until = now + RADARLESS_TRACK_HOLD_TIME
    elif radar:
      self.radarless_follow_hold_until = 0.0

    if not following_lead and matched_follow and now < self.radarless_follow_hold_until:
      following_lead = True

    self.tracking_lead_filter.update(following_lead)
    return self.tracking_lead_filter.x >= THRESHOLD

  @staticmethod
  def in_committed_turn_scene(v_ego: float, carstate, driving_in_curve: bool = False) -> bool:
    if bool(getattr(carstate, "standstill", False)) or v_ego > TURN_STOP_LIGHT_VETO_MAX_SPEED:
      return False
    if not (bool(getattr(carstate, "leftBlinker", False)) or bool(getattr(carstate, "rightBlinker", False))):
      return False
    steering_angle = abs(float(getattr(carstate, "steeringAngleDeg", 0.0)))
    return bool(steering_angle >= TURN_STOP_LIGHT_VETO_STEERING_ANGLE or driving_in_curve)

  def update(self, carstate, model_v2, lead_one=None, now: float | None = None,
             model_time: float = MODEL_TIME_NO_CEM) -> bool:
    now = time.monotonic() if now is None else now
    pos = getattr(model_v2, "position", None)
    pos_x = getattr(pos, "x", []) if pos is not None else []
    if len(pos_x) == 0:
      return self.stop_light_detected

    v_ego = max(float(getattr(carstate, "vEgo", 0.0)), 0.0)
    model_length = float(pos_x[-1])
    model_stopped = model_length < CRUISING_SPEED * PLANNER_TIME
    road_curvature = calculate_road_curvature(model_v2, v_ego)
    blinker_on = bool(getattr(carstate, "leftBlinker", False)) or bool(getattr(carstate, "rightBlinker", False))
    driving_in_curve = (
      abs(road_curvature) > 1e-6 and (1.0 / abs(road_curvature)) ** 0.5 < v_ego > CRUISING_SPEED and not blinker_on
    )

    if not bool(getattr(carstate, "standstill", False)):
      self.tracking_lead = self._update_lead_status(v_ego, model_length, model_v2, lead_one, now)

    if self.in_committed_turn_scene(v_ego, carstate, driving_in_curve):
      self.reset()
      return False

    speed_mph = v_ego * CV.MS_TO_MPH
    if speed_mph > 75.0:
      self.reset()
      return False

    bp = [0.0, 35.0, 45.0]
    filter_time_lights = _interp(speed_mph, bp, [LOW_SPEED_LIGHT_FILTER_TIME, LOW_SPEED_LIGHT_FILTER_TIME, FILTER_TIME_LIGHTS[1]])
    lead_clear_filter_time = _interp(speed_mph, bp, [LEAD_CLEAR_FILTER_TIME_LOW, LEAD_CLEAR_FILTER_TIME_LOW, LEAD_CLEAR_FILTER_TIME_HIGH])
    light_boost = _interp(speed_mph, bp, [1.0, 1.0, LIGHT_BOOSTS[1]])
    cap_factor = _interp(speed_mph, bp, [0.0, 0.0, 1.0])

    self.stop_light_filter.update_alpha(filter_time_lights)
    self.lead_clear_filter.update_alpha(lead_clear_filter_time)

    adjusted_model_time = model_time * light_boost
    if cap_factor > 0.0:
      adjusted_model_time = min(adjusted_model_time, LIGHT_MAX_TIME * cap_factor + model_time * (1.0 - cap_factor))

    stop_threshold = max(v_ego * adjusted_model_time, 0.0)
    if self.stop_light_model_detected:
      model_stopping = model_length < stop_threshold + STOP_LIGHT_OFF_MARGIN
    else:
      model_stopping = model_length < max(stop_threshold - STOP_LIGHT_ON_MARGIN, 0.0)
    self.stop_light_model_detected = model_stopping

    lead_status = bool(getattr(lead_one, "status", False)) if lead_one is not None else False
    lead_distance = float(getattr(lead_one, "dRel", float("inf"))) if lead_one is not None else float("inf")
    lead_speed = float(getattr(lead_one, "vLead", float("inf"))) if lead_one is not None else float("inf")
    lead_radar = bool(getattr(lead_one, "radar", False)) if lead_one is not None else False
    lead_prob = float(getattr(lead_one, "modelProb", 1.0 if lead_radar else 0.0)) if lead_one is not None else 0.0
    lead_relevant = lead_status and lead_distance < stop_threshold + STOP_LIGHT_LEAD_BLOCK_MARGIN

    try:
      model_accel = float(model_v2.action.desiredAcceleration)
    except (AttributeError, TypeError, ValueError):
      model_accel = 0.0

    model_target_before_lead = bool(
      model_stopping and lead_relevant and v_ego > CRUISING_SPEED and
      model_accel <= -STOP_LIGHT_MODEL_BRAKE_MIN and
      model_length + STOP_LIGHT_MODEL_LEAD_MARGIN < lead_distance
    )
    vision_stop_approach = (
      lead_relevant and not lead_radar and
      lead_prob >= STOP_APPROACH_MIN_MODEL_PROB and
      lead_speed < STOP_APPROACH_MAX_LEAD_SPEED
    )
    stop_approach_hold_active = now < self.stop_approach_hold_until
    trackable_stop_approach = vision_stop_approach and not self.tracking_lead
    if (self.stop_light_detected or self.stop_light_model_detected or stop_approach_hold_active) and trackable_stop_approach:
      self.stop_approach_hold_until = now + STOP_APPROACH_LATCH_TIME
    stop_approach_latched = now < self.stop_approach_hold_until and trackable_stop_approach
    handoff_to_stopped_lead = (
      lead_relevant and not self.tracking_lead and (
        (self.stop_light_detected and lead_speed < STOP_LIGHT_HANDOFF_MAX_LEAD_SPEED) or
        stop_approach_latched
      )
    )
    if handoff_to_stopped_lead or model_target_before_lead:
      lead_cleared = True
    else:
      self.lead_clear_filter.update(not lead_relevant)
      lead_cleared = self.lead_clear_filter.x >= THRESHOLD

    self.stop_light_filter.update(model_stopping and lead_cleared)
    model_detector_active = bool(self.stop_light_filter.x >= THRESHOLD ** 2 and lead_cleared)
    detector_active = bool(model_detector_active or handoff_to_stopped_lead or stop_approach_latched)
    model_hold_qualifies = bool(
      model_stopped or model_length < max(stop_threshold - STOP_LIGHT_MODEL_HOLD_STRONG_MARGIN, 0.0)
    )
    if model_detector_active and model_hold_qualifies:
      self.stop_light_detected_hold_until = now + STOP_LIGHT_DETECTED_HOLD_TIME

    hold_context_ok = bool((not lead_relevant) or trackable_stop_approach or model_target_before_lead)
    self.stop_light_detected = bool(
      detector_active or (hold_context_ok and now < self.stop_light_detected_hold_until)
    )
    return self.stop_light_detected
