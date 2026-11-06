"""
Set Speed Assist, from sunnypilot PR #2083 by Zeph Leggett (MIT).
https://github.com/sunnypilot/sunnypilot/pull/2083
"""
import numpy as np

from opendbc.car import rate_limit
from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants

LaneChangeState = log.LaneChangeState

PARAM = "SetSpeedAssist"
PARAMS_UPDATE_PERIOD = 3.  # s
MIN_SPEED = 5.  # m/s. No assist below this, so stop-and-go stays with the model.
FULL_SPEED = 8.  # m/s. Full assist from this speed up.
GAIN_BP = [-0.3, -0.1]  # Model accel over which the assist fades out as the model slows down.
FADE_LAT_ACC_BP = [0.6, 1.0]  # Lat acc of the sharpest bend ahead over which the assist fades out.
LIFT_FALL = 2.4  # m/s^3. Fast, so the assist never holds off the model's braking.
# Approach pace: CX-5 MRCC no-lead p99 acceleration by speed, scaled by speed shortfall.
# This avoids the cruise planner's aggressive acceleration for small gaps.
APPROACH_BP = [0., 4., 9., 14., 18., 25.]  # m/s
APPROACH_V = [1.5, 1.75, 1.45, 1.05, 0.85, 0.65]  # m/s^2
APPROACH_GAP_BP = [0., 1., 3., 5., 10.]  # m/s under the target speed
APPROACH_GAP_FRACTION = [0.38, 0.47, 0.57, 0.72, 1.]


def approach_accel(v_ego: float, v_target: float) -> float:
  """The most the floor asks while closing on v_target."""
  return float(np.interp(v_ego, APPROACH_BP, APPROACH_V) * np.interp(v_target - v_ego, APPROACH_GAP_BP, APPROACH_GAP_FRACTION))


class SetSpeedAssist:
  """
  The driving model doesn't know the set speed, so it often drives below it, or further back from
  a lead than the personality's gap. This adds acceleration to the model's, up to what the lead and
  cruise planners would do, while the model isn't slowing down. It never takes any away.
  Only with openpilot longitudinal control: the toggle does nothing otherwise.
  """
  def __init__(self, CP):
    # Local import avoids a cycle with longitudinal_planner.
    from openpilot.selfdrive.controls.lib.longitudinal_planner import J_CRUISE_BP, J_CRUISE_VALS
    self.rise_bp, self.rise_vals = J_CRUISE_BP, J_CRUISE_VALS

    self.allowed = bool(CP.openpilotLongitudinalControl)
    self.params = Params()
    self.frame = -1
    self.enabled = self._read_enabled()
    self.active = False
    self.gain = 0.
    self.fade = 0.
    self.lift = 0.

  def _read_enabled(self) -> bool:
    return self.allowed and self.params.get_bool(PARAM)

  def update(self, sm, a_model: float, a_floor: float, reset_state: bool) -> float:
    """Return the model's accel plus the assist. a_floor is the lower of the lead and cruise accels and the approach pace."""
    self.frame += 1
    if self.frame % int(PARAMS_UPDATE_PERIOD / DT_MDL) == 0:
      self.enabled = self._read_enabled()

    self.active = False
    self.gain = self.fade = 0.
    # when switched off, the assist eases out at LIFT_FALL before stopping
    if not self.allowed or reset_state or (not self.enabled and self.lift == 0.):
      self.lift = 0.
      return a_model

    md = sm['modelV2']
    v_ego = sm['carState'].vEgo
    vel = np.asarray(md.velocity.x)
    yaw_rate = np.asarray(md.orientationRate.z)
    gas_press_probs = md.meta.disengagePredictions.gasPressProbs
    throttle_prob = gas_press_probs[1] if len(gas_press_probs) > 1 else 1.
    curvatures = [md.action.desiredCurvature, sm['controlsState'].curvature]
    if not (len(vel) == len(yaw_rate) == ModelConstants.IDX_N and
            np.isfinite(np.concatenate([vel, yaw_rate, [v_ego, a_model, a_floor, throttle_prob, *curvatures]])).all()):
      self.lift = 0.
      return a_model

    # sharpest bend now or along the model's path, at the current speed
    curvature = max(*np.abs(curvatures), np.max(np.abs(yaw_rate) / np.maximum(vel, 1.)))
    lat_acc = curvature * v_ego ** 2

    self.gain = np.interp(a_model, GAIN_BP, [0., 1.]) * throttle_prob * np.interp(v_ego, [MIN_SPEED, FULL_SPEED], [0., 1.])
    self.fade = np.interp(lat_acc, FADE_LAT_ACC_BP, [1., 0.])
    self.active = self.enabled and md.meta.laneChangeState == LaneChangeState.off

    target = self.gain * self.fade * max(0., a_floor - a_model) if self.active else 0.
    rise = np.interp(v_ego, self.rise_bp, self.rise_vals)
    self.lift = rate_limit(target, self.lift, -LIFT_FALL * DT_MDL, rise * DT_MDL)
    return a_model + self.lift
