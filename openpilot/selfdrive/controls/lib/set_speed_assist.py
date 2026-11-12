"""
Set Speed Assist, from sunnypilot PR #2083 by Zeph Leggett (MIT).
https://github.com/sunnypilot/sunnypilot/pull/2083
"""
import math

import numpy as np

from opendbc.car import rate_limit
from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants

LaneChangeState = log.LaneChangeState
Personality = log.LongitudinalPersonality

PARAM = "SetSpeedAssist"
PARAMS_UPDATE_PERIOD = 3.  # s
MIN_SPEED = 5.  # m/s. No assist below this, so stop-and-go stays with the model.
FULL_SPEED = 8.  # m/s. Full assist from this speed up.
GAIN_BP = [-0.3, -0.1]  # Model accel over which the assist fades out as the model slows down.
FADE_LAT_ACC_BP = [0.6, 1.0]  # Lat acc of the sharpest bend ahead over which the assist fades out.
LIFT_FALL = 2.4  # m/s^3. Slowest the lift eases off, e.g. on a lane change or a bend.
# CX-5 MRCC no-lead p99 accel by speed. Under that ceiling, a jerk-limited arrival
# that reaches the target with none left: sqrt(2 * jerk * gap).
APPROACH_BP = [0., 4., 9., 14., 18., 25.]  # m/s
APPROACH_V = [1.5, 1.75, 1.45, 1.05, 0.85, 0.65]  # m/s^2
APPROACH_JERK = 0.065  # m/s^3
# The table is Standard; Relaxed / Aggressive move the ceiling by AccelBoostSP's step.
APPROACH_PERSONALITY_OFFSET = {
  Personality.relaxed: -0.15,
  Personality.standard: 0.,
  Personality.aggressive: 0.15,
}  # m/s^2
HORIZON = 10.  # s. Plan look-ahead for a slowdown and for the bend check.
LEAD_TTC_BP = [15., 25.]  # s. A closing lead counts in full under 15 s, not at all past 25 s.
T_IDXS = np.asarray(ModelConstants.T_IDXS)
HORIZON_MASK = T_IDXS <= HORIZON


def _personality_offset(personality) -> float:
  if personality == Personality.relaxed:
    return APPROACH_PERSONALITY_OFFSET[Personality.relaxed]
  if personality == Personality.aggressive:
    return APPROACH_PERSONALITY_OFFSET[Personality.aggressive]
  return APPROACH_PERSONALITY_OFFSET[Personality.standard]


def approach_accel(v_ego: float, v_target: float, personality) -> float:
  ceiling = np.interp(v_ego, APPROACH_BP, APPROACH_V) + _personality_offset(personality)
  return min(math.sqrt(2. * APPROACH_JERK * max(v_target - v_ego, 0.)), float(ceiling))


def planned_slowdown(v_ego: float, plan_v: np.ndarray, lead) -> float:
  # m/s the car is set to shed over the horizon: the plan's lowest speed, or a closing lead.
  drop = v_ego - float(np.min(plan_v[HORIZON_MASK]))
  if lead.present and math.isfinite(lead.vRel) and math.isfinite(lead.dRel) and lead.vRel < 0.:
    ttc = max(lead.dRel, 0.) / -lead.vRel
    drop = max(drop, -lead.vRel * float(np.interp(ttc, LEAD_TTC_BP, [1., 0.])))
  return drop


class SetSpeedAssist:
  # The driving model doesn't know the set speed, so it often drives below it, or further back from
  # a lead than the personality's gap. This adds acceleration to the model's, up to what the lead and
  # cruise planners would do, while the model isn't slowing down. It never takes any away.
  # Only with openpilot longitudinal control: the toggle does nothing otherwise.
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
    self.plan_fade = 0.
    self.lift = 0.

  def _read_enabled(self) -> bool:
    return self.allowed and self.params.get_bool(PARAM)

  def update_params(self) -> None:
    # Called before the planner decides whether AccelBoost may run, so both never run on the same frame.
    self.frame += 1
    if self.frame % int(PARAMS_UPDATE_PERIOD / DT_MDL) == 0:
      self.enabled = self._read_enabled()

  def update(self, sm, a_model: float, a_floor: float, reset_state: bool) -> float:
    self.active = False
    self.gain = self.fade = self.plan_fade = 0.
    # when switched off, the assist eases out at LIFT_FALL before stopping
    if not self.allowed or reset_state or (not self.enabled and self.lift == 0.):
      self.lift = 0.
      return a_model

    md = sm['modelV2']
    v_ego = sm['carState'].vEgo
    vel = np.asarray(md.velocity.x)
    yaw_rate = np.asarray(md.orientationRate.z)
    curvature_now = sm['controlsState'].curvature
    if not (len(vel) == len(yaw_rate) == ModelConstants.IDX_N and
            np.isfinite(np.concatenate([vel, yaw_rate, [v_ego, a_model, a_floor, curvature_now]])).all()):
      self.lift = 0.
      return a_model

    # sharpest bend now or along the model's path, at the current speed
    curvature = max(abs(curvature_now), np.max(np.abs(yaw_rate[HORIZON_MASK]) / np.maximum(vel[HORIZON_MASK], 1.)))
    lat_acc = curvature * v_ego ** 2

    self.plan_fade = float(np.interp(-planned_slowdown(v_ego, vel, sm['radarState'].leadOne) / HORIZON, GAIN_BP, [0., 1.]))
    self.gain = (min(float(np.interp(a_model, GAIN_BP, [0., 1.])), self.plan_fade) *
                 float(np.interp(v_ego, [MIN_SPEED, FULL_SPEED], [0., 1.])))
    self.fade = float(np.interp(lat_acc, FADE_LAT_ACC_BP, [1., 0.]))
    self.active = self.enabled and md.meta.laneChangeState == LaneChangeState.off

    target = self.gain * self.fade * max(0., a_floor - a_model) if self.active else 0.
    rise = np.interp(v_ego, self.rise_bp, self.rise_vals)
    # Normally eases off at LIFT_FALL. When the model (or its plan) starts to brake, the gain
    # drops and the lift may drop with it in one frame, so at gain 0 the model's braking is not delayed.
    fall = max(LIFT_FALL * DT_MDL, (1. - self.gain) * self.lift)
    self.lift = rate_limit(target, self.lift, -fall, rise * DT_MDL)
    return a_model + self.lift
