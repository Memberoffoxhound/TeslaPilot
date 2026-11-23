from types import SimpleNamespace

from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.conftest import FakeParams
from openpilot.selfdrive.controls.lib import auto_lane_change as alc
from openpilot.selfdrive.controls.lib import desire_helper as dh
from openpilot.selfdrive.controls.lib.stop_light_detector import StopLightDetector


def _cs(v_ego=5.0, left=False, right=False, standstill=False, steer_deg=0.0):
  return SimpleNamespace(
    vEgo=v_ego,
    leftBlinker=left,
    rightBlinker=right,
    standstill=standstill,
    steeringPressed=False,
    steeringTorque=0.0,
    leftBlindspot=False,
    rightBlindspot=False,
    brakePressed=False,
    steeringAngleDeg=steer_deg,
  )


def _make_helper(monkeypatch, turn_desires=True, alc_on=False):
  p = FakeParams(TurnDesires=turn_desires, AutoLaneChangeEnabled=alc_on)
  monkeypatch.setattr(dh, "Params", lambda *a, **k: p)
  monkeypatch.setattr(alc, "Params", lambda *a, **k: p)
  return dh.DesireHelper()


def test_turn_desire_default_off(monkeypatch):
  p = FakeParams()
  monkeypatch.setattr(dh, "Params", lambda *a, **k: p)
  monkeypatch.setattr(alc, "Params", lambda *a, **k: p)
  helper = dh.DesireHelper()
  assert not helper.turn_desires
  helper.update(_cs(v_ego=5.0, right=True), True, 0.0)
  assert helper.desire == log.Desire.none


def test_turn_desire_fires_immediately_below_20_mph(monkeypatch):
  helper = _make_helper(monkeypatch, turn_desires=True)
  # first frame with blinker fires immediately (no debounce)
  helper.update(_cs(v_ego=19.9 * CV.MPH_TO_MS, right=True), True, 0.0)
  assert helper.desire == log.Desire.turnRight
  assert helper.turn_direction == log.Desire.turnRight
  helper.update(_cs(v_ego=5.0, left=True), True, 0.0)
  assert helper.desire == log.Desire.turnLeft


def test_speed_band_20_to_45_mph_and_45_lane_change(monkeypatch):
  helper = _make_helper(monkeypatch, turn_desires=True, alc_on=True)
  # between 20 and 45 mph: neither turn nor lane change
  for _ in range(100):
    helper.update(_cs(v_ego=25.0 * CV.MPH_TO_MS, left=True), True, 0.0)
    assert helper.desire == log.Desire.none
    assert helper.lane_change_state == log.LaneChangeState.off

  # reset blinker, then verify >=45 mph lane change still works
  helper.update(_cs(v_ego=46.0 * CV.MPH_TO_MS), True, 0.0)
  started = False
  for _ in range(60):
    helper.update(_cs(v_ego=46.0 * CV.MPH_TO_MS, left=True), True, 0.0)
    if helper.lane_change_state == log.LaneChangeState.laneChangeStarting:
      started = True
      break
  assert started
  assert helper.desire == log.Desire.laneChangeLeft


def test_turn_stop_hold_red_light_clears_at_standstill(monkeypatch):
  helper = _make_helper(monkeypatch, turn_desires=True)
  helper.update(_cs(v_ego=5.0, right=True), True, 0.0, red_light=True)
  assert helper.turn_stop_hold
  assert helper.desire == log.Desire.none

  # held while slowing even if red_light momentarily drops
  helper.update(_cs(v_ego=2.0, right=True), True, 0.0, red_light=False)
  assert helper.turn_stop_hold
  assert helper.desire == log.Desire.none

  # standstill clears hold, rolling out with blinker fires turn
  helper.update(_cs(v_ego=0.0, right=True, standstill=True), True, 0.0, red_light=True)
  assert not helper.turn_stop_hold
  helper.update(_cs(v_ego=2.0, right=True), True, 0.0)
  assert helper.desire == log.Desire.turnRight


def test_turn_stop_hold_forcing_stop_and_cancel(monkeypatch):
  helper = _make_helper(monkeypatch, turn_desires=True)
  helper.update(_cs(v_ego=5.0, left=True), True, 0.0, forcing_stop=True)
  assert helper.turn_stop_hold
  assert helper.desire == log.Desire.none

  # cancelling blinker clears hold
  helper.update(_cs(v_ego=5.0), True, 0.0)
  assert not helper.turn_stop_hold
  helper.update(_cs(v_ego=5.0, left=True), True, 0.0)
  assert helper.desire == log.Desire.turnLeft


def _model_v2(length_m, accel=0.0):
  xs = [length_m * i / 32.0 for i in range(33)]
  zeros = [0.0] * 33
  return SimpleNamespace(
    position=SimpleNamespace(x=xs, y=zeros),
    orientationRate=SimpleNamespace(z=zeros),
    velocity=SimpleNamespace(x=[10.0] * 33),
    action=SimpleNamespace(desiredAcceleration=accel),
  )


def test_stop_light_detector_true_and_lead_block():
  det = StopLightDetector()
  cs = _cs(v_ego=10.0, right=True)
  # horizon 20 m << 80 m (10 m/s * 8 s) with no lead -> triggers after ~1 s filter
  for i in range(60):
    detected = det.update(cs, _model_v2(20.0), now=100.0 + i * 0.05)
  assert detected

  # relevant lead at 22 m blocks stop-light inference on a fresh detector
  det2 = StopLightDetector()
  lead = SimpleNamespace(status=True, dRel=22.0, vLead=9.0, radar=True, modelProb=1.0, yRel=0.0, aLeadK=0.0)
  for i in range(60):
    detected2 = det2.update(cs, _model_v2(20.0, accel=0.0), lead_one=lead, now=200.0 + i * 0.05)
  assert not detected2


def test_stop_light_detector_committed_turn_veto():
  det = StopLightDetector()
  cs_turning = _cs(v_ego=5.0, right=True, steer_deg=55.0)
  for i in range(40):
    assert not det.update(cs_turning, _model_v2(15.0), now=300.0 + i * 0.05)
