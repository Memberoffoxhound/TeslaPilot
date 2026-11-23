from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.params_compat import get_bool
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.auto_lane_change import AutoLaneChangeController

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

# Highland lane change floor 45 mph (stock 20); StarPilot turn cap 20 mph.
LANE_CHANGE_SPEED_MIN = 45 * CV.MPH_TO_MS
TURN_SPEED_MAX = 20 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.
LANE_CHANGE_START_TIME = 0.5

class DesireHelper:
  def __init__(self):
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.prev_one_blinker = False
    self.desire = log.Desire.none
    self.turn_direction = log.Desire.none
    self.turn_stop_hold = False
    self.params = Params()
    self.turn_desires = False
    self._param_read_counter = 0
    self.alc = AutoLaneChangeController(self)
    self._read_params()

  def _read_params(self):
    self.turn_desires = get_bool(self.params, "TurnDesires", False)

  def _update_params(self):
    if self._param_read_counter % 50 == 0:
      self._read_params()
    self._param_read_counter += 1

  @staticmethod
  def get_lane_change_direction(CS):
    return LaneChangeDirection.left if CS.leftBlinker else LaneChangeDirection.right

  def update(self, carstate, lateral_active, lane_change_prob, red_light=False):
    self._update_params()
    self.alc.update_params()
    v_ego = carstate.vEgo
    one_blinker = carstate.leftBlinker != carstate.rightBlinker
    standstill = carstate.standstill
    below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN
    below_turn_speed = v_ego < TURN_SPEED_MAX

    stop_imminent = bool(red_light)
    if standstill or not one_blinker:
      self.turn_stop_hold = False
    elif stop_imminent:
      self.turn_stop_hold = True

    if not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX:
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.lane_change_timer = 0.0
    else:
      if self.lane_change_state == LaneChangeState.off and one_blinker and not self.prev_one_blinker and not below_lane_change_speed:
        self.lane_change_state = LaneChangeState.preLaneChange
        self.lane_change_timer = 0.0
        # Initialize lane change direction to prevent UI alert flicker
        self.lane_change_direction = self.get_lane_change_direction(carstate)

      elif self.lane_change_state == LaneChangeState.preLaneChange:
        # Update lane change direction
        self.lane_change_direction = self.get_lane_change_direction(carstate)

        torque_applied = carstate.steeringPressed and \
                         ((carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                          (carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

        blindspot_detected = ((carstate.leftBlindspot and self.lane_change_direction == LaneChangeDirection.left) or
                              (carstate.rightBlindspot and self.lane_change_direction == LaneChangeDirection.right))

        self.alc.update_lane_change(blindspot_detected, carstate.brakePressed)

        if not one_blinker or below_lane_change_speed:
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
          self.lane_change_timer = 0.0
        elif (torque_applied or self.alc.auto_lane_change_allowed) and not blindspot_detected:
          self.lane_change_state = LaneChangeState.laneChangeStarting
          self.lane_change_timer = 0.0

      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        self.lane_change_timer += DT_MDL

        if lane_change_prob < 0.02 and self.lane_change_timer >= LANE_CHANGE_START_TIME:
          self.lane_change_timer = 0.0
          if one_blinker:
            self.lane_change_state = LaneChangeState.preLaneChange
            self.lane_change_direction = self.get_lane_change_direction(carstate)
          else:
            self.lane_change_state = LaneChangeState.off
            self.lane_change_direction = LaneChangeDirection.none

    self.prev_one_blinker = one_blinker and lateral_active

    if (lateral_active and one_blinker and below_turn_speed and not standstill and self.turn_desires
        and not self.turn_stop_hold):
      self.turn_direction = log.Desire.turnLeft if carstate.leftBlinker else log.Desire.turnRight
      self.desire = self.turn_direction
    else:
      self.turn_direction = log.Desire.none
      self.desire = log.Desire.none
      if self.lane_change_state == LaneChangeState.laneChangeStarting:
        if self.lane_change_direction == LaneChangeDirection.left:
          self.desire = log.Desire.laneChangeLeft
        elif self.lane_change_direction == LaneChangeDirection.right:
          self.desire = log.Desire.laneChangeRight

    self.alc.update_state()
