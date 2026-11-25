import sys
import types
from types import SimpleNamespace

from openpilot.conftest import FakeParams

try:
  from openpilot.common.params import Params  # noqa: F401
except (ImportError, OSError):
  stub = types.ModuleType("openpilot.common.params")
  stub.Params = FakeParams
  sys.modules["openpilot.common.params"] = stub
  for name in (
    "openpilot.selfdrive.controls.lib.auto_lane_change",
    "openpilot.selfdrive.controls.lib.desire_helper",
    "openpilot.selfdrive.controls.lib.turn_intent",
    "openpilot.selfdrive.controls.lib.signal_turn",
  ):
    sys.modules.pop(name, None)

from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.selfdrive.controls.lib import auto_lane_change as alc
from openpilot.selfdrive.controls.lib import desire_helper as dh
from openpilot.selfdrive.controls.lib.turn_intent import TurnIntent
from openpilot.selfdrive.controls.lib.signal_turn import CONFIRM_NS, MAX_AGE_NS, SignalTurnEvidence


def _cs(v_ego=5.0, left=False, right=False, standstill=False, a_ego=-1.0,
        left_blind=False, right_blind=False, steer_pressed=False):
  return SimpleNamespace(
    vEgo=v_ego,
    aEgo=a_ego,
    leftBlinker=left,
    rightBlinker=right,
    standstill=standstill,
    steeringPressed=steer_pressed,
    steeringTorque=0.0,
    leftBlindspot=left_blind,
    rightBlindspot=right_blind,
    brakePressed=False,
    steerFaultTemporary=False,
    steerFaultPermanent=False,
  )


def _cc(lat_active=True):
  return SimpleNamespace(latActive=lat_active)


def _plan(should_stop=False):
  return SimpleNamespace(shouldStop=should_stop)


def _nav(typ="turn", modifier="right", distance=40.0):
  return SimpleNamespace(maneuverType=typ, maneuverModifier=modifier, maneuverDistance=distance)


class FakeSM:
  def __init__(self, cs, cc, plan=None, nav=None, valid=True):
    self._d = {
      "carState": cs,
      "carControl": cc,
      "longitudinalPlan": plan if plan is not None else _plan(),
      "navInstruction": nav,
    }
    self.valid = {k: valid for k in self._d}
    self.alive = {k: valid for k in self._d}
    self.seen = {k: True for k in self._d}

  def __getitem__(self, key):
    return self._d[key]

  def __contains__(self, key):
    return key in self._d


def _intent(force=True, model_confirm=False, nav=False):
  p = FakeParams(TurnDesires=force, TurnDesiresModelConfirm=model_confirm, TurnDesiresNav=nav)
  return TurnIntent(params=p)


def _make_helper(monkeypatch, alc_on=False):
  p = FakeParams(AutoLaneChangeEnabled=alc_on)
  monkeypatch.setattr(alc, "Params", lambda *a, **k: p)
  return dh.DesireHelper()


def test_force_default_off():
  intent = _intent(force=False)
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc())
  assert intent.select(sm, 1_000_000, log.Desire.none) == log.Desire.none


def test_force_fires_immediately_below_20_mph():
  intent = _intent(force=True)
  sm = FakeSM(_cs(v_ego=19.9 * CV.MPH_TO_MS, right=True), _cc())
  assert intent.select(sm, 1_000_000, log.Desire.none) == log.Desire.turnRight
  sm = FakeSM(_cs(v_ego=5.0, left=True), _cc())
  assert intent.select(sm, 2_000_000, log.Desire.none) == log.Desire.turnLeft


def test_force_requires_blinker_and_clears():
  intent = _intent(force=True)
  assert intent.select(FakeSM(_cs(v_ego=5.0), _cc()), 1, log.Desire.none) == log.Desire.none
  assert intent.select(FakeSM(_cs(v_ego=5.0, right=True), _cc()), 2, log.Desire.none) == log.Desire.turnRight
  assert intent.select(FakeSM(_cs(v_ego=5.0), _cc()), 3, log.Desire.none) == log.Desire.none


def test_force_blocked_by_blindspot():
  intent = _intent(force=True)
  assert intent.select(FakeSM(_cs(v_ego=5.0, right=True, right_blind=True), _cc()), 1, log.Desire.none) == log.Desire.none
  assert intent.select(FakeSM(_cs(v_ego=5.0, left=True, left_blind=True), _cc()), 2, log.Desire.none) == log.Desire.none
  assert intent.select(FakeSM(_cs(v_ego=5.0, right=True), _cc()), 3, log.Desire.none) == log.Desire.turnRight


def test_force_not_at_20_to_45_without_model_confirm():
  intent = _intent(force=True, model_confirm=False)
  for mph in (20.0, 25.0, 31.0, 44.9):
    sm = FakeSM(_cs(v_ego=mph * CV.MPH_TO_MS, left=True, a_ego=-1.0), _cc())
    assert intent.select(sm, 1, log.Desire.none) == log.Desire.none


def test_lane_change_still_starts_at_45(monkeypatch):
  helper = _make_helper(monkeypatch, alc_on=True)
  helper.update(_cs(v_ego=46.0 * CV.MPH_TO_MS), True, 0.0)
  started = False
  for _ in range(60):
    helper.update(_cs(v_ego=46.0 * CV.MPH_TO_MS, left=True), True, 0.0)
    if helper.lane_change_state == log.LaneChangeState.laneChangeStarting:
      started = True
      break
  assert started
  assert helper.desire == log.Desire.laneChangeLeft


def test_stop_hold_from_plan_clears_at_standstill():
  intent = _intent(force=True)
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc(), plan=_plan(True))
  assert intent.select(sm, 1, log.Desire.none, model_stop=False) == log.Desire.none
  assert intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=2.0, right=True), _cc(), plan=_plan(False))
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none
  assert intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=0.0, right=True, standstill=True), _cc(), plan=_plan(True))
  assert intent.select(sm, 3, log.Desire.none, model_stop=True) == log.Desire.none
  assert not intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=2.0, right=True), _cc())
  assert intent.select(sm, 4, log.Desire.none) == log.Desire.turnRight
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc())
  assert intent.select(sm, 5, log.Desire.none, model_stop=True) == log.Desire.none
  sm = FakeSM(_cs(v_ego=5.0), _cc())
  assert intent.select(sm, 6, log.Desire.none) == log.Desire.none
  assert not intent.signal_stop_hold


def _prediction(turn=log.Desire.turnRight, prob=0.8, opposite=0.05, lane=0.05):
  slices = []
  for _ in range(4):
    row = [0.0] * 8
    remain = 1.0 - prob - opposite - lane
    row[int(log.Desire.none)] = remain
    row[int(turn)] = prob
    row[int(log.Desire.turnLeft if turn == log.Desire.turnRight else log.Desire.turnRight)] = opposite
    row[int(log.Desire.laneChangeRight if turn == log.Desire.turnRight else log.Desire.laneChangeLeft)] = lane
    slices.extend(row)
  return slices


def _model(pred=None, should_stop=False, lane_state=None):
  return SimpleNamespace(
    action=SimpleNamespace(shouldStop=should_stop),
    meta=SimpleNamespace(
      desirePrediction=pred if pred is not None else _prediction(),
      laneChangeState=lane_state if lane_state is not None else log.LaneChangeState.off,
    ),
  )


def test_model_confirm_needs_forecast_and_decel():
  intent = _intent(force=True, model_confirm=True)
  v = 25.0 * CV.MPH_TO_MS
  cs = _cs(v_ego=v, right=True, a_ego=-1.0)
  cc = _cc()
  plan = _plan(False)
  sm = FakeSM(cs, cc, plan=plan)
  # no evidence yet
  assert intent.select(sm, 1_000_000, log.Desire.none) == log.Desire.none
  ev = intent.signal_model
  ev.observe(cs, cc, _model(), model_ns=1_000_000, now_ns=1_000_000, plan=plan)
  assert not ev.ready
  ev.observe(cs, cc, _model(), model_ns=1_000_000 + CONFIRM_NS, now_ns=1_000_000 + CONFIRM_NS, plan=plan)
  assert ev.ready
  now = 1_000_000 + CONFIRM_NS
  assert intent.select(sm, now, log.Desire.none) == log.Desire.turnRight
  # accelerating: no evidence
  ev.reset()
  cs_accel = _cs(v_ego=v, right=True, a_ego=0.2)
  ev.observe(cs_accel, cc, _model(), model_ns=now, now_ns=now, plan=plan)
  assert not ev.ready
  assert intent.select(FakeSM(cs_accel, cc, plan=plan), now, log.Desire.none) == log.Desire.none


def test_model_confirm_rejects_weak_or_lane_change_forecast():
  ev = SignalTurnEvidence()
  v = 25.0 * CV.MPH_TO_MS
  cs = _cs(v_ego=v, right=True, a_ego=-1.0)
  cc = _cc()
  plan = _plan(False)
  weak = _model(_prediction(prob=0.4, opposite=0.05, lane=0.05))
  ev.observe(cs, cc, weak, model_ns=1, now_ns=1, plan=plan)
  ev.observe(cs, cc, weak, model_ns=1 + CONFIRM_NS, now_ns=1 + CONFIRM_NS, plan=plan)
  assert not ev.ready
  lane = _model(_prediction(prob=0.7, opposite=0.05, lane=0.25))
  ev.observe(cs, cc, lane, model_ns=10, now_ns=10, plan=plan)
  ev.observe(cs, cc, lane, model_ns=10 + CONFIRM_NS, now_ns=10 + CONFIRM_NS, plan=plan)
  assert not ev.ready
  # above ~31 mph, even a strong forecast is ignored
  ev.reset()
  cs_fast = _cs(v_ego=32.0 * CV.MPH_TO_MS, right=True, a_ego=-1.0)
  ev.observe(cs_fast, cc, _model(), model_ns=20, now_ns=20, plan=plan)
  ev.observe(cs_fast, cc, _model(), model_ns=20 + CONFIRM_NS, now_ns=20 + CONFIRM_NS, plan=plan)
  assert not ev.ready


def test_model_confirm_ignores_steering_pressed():
  intent = _intent(force=True, model_confirm=True)
  v = 25.0 * CV.MPH_TO_MS
  cs = _cs(v_ego=v, right=True, a_ego=-1.0)
  cc = _cc()
  plan = _plan(False)
  ev = intent.signal_model
  ev.observe(cs, cc, _model(), model_ns=1, now_ns=1, plan=plan)
  ev.observe(cs, cc, _model(), model_ns=1 + CONFIRM_NS, now_ns=1 + CONFIRM_NS, plan=plan)
  now = 1 + CONFIRM_NS
  assert intent.select(FakeSM(cs, cc, plan=plan), now, log.Desire.none) == log.Desire.turnRight
  pressed = _cs(v_ego=v, right=True, a_ego=-1.0, steer_pressed=True)
  assert intent.select(FakeSM(pressed, cc, plan=plan), now, log.Desire.none) == log.Desire.none


def test_nav_turn_needs_matching_blinker():
  intent = _intent(force=True, nav=True)
  nav = _nav(modifier="right", distance=40.0)
  # 25 mph: force path off, nav can still fire
  cs = _cs(v_ego=25.0 * CV.MPH_TO_MS, right=True)
  sm = FakeSM(cs, _cc(), nav=nav)
  assert intent.select(sm, 1, log.Desire.none) == log.Desire.turnRight
  sm = FakeSM(_cs(v_ego=25.0 * CV.MPH_TO_MS, left=True), _cc(), nav=nav)
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none
  sm = FakeSM(_cs(v_ego=25.0 * CV.MPH_TO_MS, right=True), _cc(), nav=_nav(typ="depart", modifier="right"))
  assert intent.select(sm, 3, log.Desire.none) == log.Desire.none
  # sharp left with a space, as Mapbox may send
  sm = FakeSM(_cs(v_ego=10.0, left=True), _cc(), nav=_nav(modifier="sharp left", distance=30.0))
  assert intent.select(sm, 4, log.Desire.none) == log.Desire.turnLeft
  # off when nav toggle is off, 25 mph has no force path
  intent_off = _intent(force=True, nav=False)
  sm = FakeSM(_cs(v_ego=25.0 * CV.MPH_TO_MS, right=True), _cc(), nav=nav)
  assert intent_off.select(sm, 5, log.Desire.none) == log.Desire.none


def test_nav_respects_distance_and_blindspot():
  intent = _intent(force=True, nav=True)
  sm = FakeSM(_cs(v_ego=10.0, right=True), _cc(), nav=_nav(distance=200.0))
  assert intent.select(sm, 1, log.Desire.none) == log.Desire.none
  sm = FakeSM(_cs(v_ego=10.0, right=True, right_blind=True), _cc(), nav=_nav(distance=40.0))
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none


def test_select_does_not_override_lane_change():
  intent = _intent(force=True)
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc())
  assert intent.select(sm, 1, log.Desire.laneChangeRight) == log.Desire.laneChangeRight


def test_nav_should_stop_flicker_holds():
  intent = _intent(force=True, nav=True)
  nav = _nav(modifier="right", distance=40.0)
  v = 25.0 * CV.MPH_TO_MS
  sm = FakeSM(_cs(v_ego=v, right=True), _cc(), plan=_plan(True), nav=nav)
  assert intent.select(sm, 1, log.Desire.none) == log.Desire.none
  assert intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=v, right=True), _cc(), plan=_plan(False), nav=nav)
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none
  assert intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=0.0, right=True, standstill=True), _cc(), plan=_plan(True), nav=nav)
  assert intent.select(sm, 3, log.Desire.none) == log.Desire.none
  assert not intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=v, right=True), _cc(), plan=_plan(False), nav=nav)
  assert intent.select(sm, 4, log.Desire.none) == log.Desire.turnRight


def test_stop_hold_clears_on_disengage():
  intent = _intent(force=True)
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc(), plan=_plan(True))
  assert intent.select(sm, 1, log.Desire.none) == log.Desire.none
  assert intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=5.0), _cc(lat_active=False), plan=_plan(False))
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none
  assert not intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc())
  assert intent.select(sm, 3, log.Desire.none) == log.Desire.turnRight


def test_stop_hold_clears_above_20_mph_when_blinker_off():
  intent = _intent(force=True, model_confirm=False)
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc(), plan=_plan(True))
  assert intent.select(sm, 1, log.Desire.none) == log.Desire.none
  assert intent.signal_stop_hold
  v = 25.0 * CV.MPH_TO_MS
  sm = FakeSM(_cs(v_ego=v, right=True), _cc(), plan=_plan(False))
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none
  assert intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=v), _cc(), plan=_plan(False))
  assert intent.select(sm, 3, log.Desire.none) == log.Desire.none
  assert not intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc())
  assert intent.select(sm, 4, log.Desire.none) == log.Desire.turnRight


def test_hazards_clear_hold_and_do_not_fire():
  intent = _intent(force=True)
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc(), plan=_plan(True))
  assert intent.select(sm, 1, log.Desire.none) == log.Desire.none
  assert intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=5.0, left=True, right=True), _cc())
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none
  assert not intent.signal_stop_hold
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc())
  assert intent.select(sm, 3, log.Desire.none) == log.Desire.turnRight


def test_parent_off_blocks_child_toggles():
  intent = _intent(force=False, model_confirm=True, nav=True)
  nav = _nav(modifier="right", distance=40.0)
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc(), nav=nav)
  assert intent.select(sm, 1, log.Desire.none) == log.Desire.none
  sm = FakeSM(_cs(v_ego=25.0 * CV.MPH_TO_MS, right=True, a_ego=-1.0), _cc(), nav=nav)
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none
  assert not intent.signal_stop_hold


def test_v_ego_at_or_below_0_1_does_not_fire():
  intent = _intent(force=True, nav=True)
  nav = _nav(modifier="right", distance=40.0)
  for v in (0.0, 0.05, 0.1):
    sm = FakeSM(_cs(v_ego=v, right=True), _cc(), nav=nav)
    assert intent.select(sm, 1, log.Desire.none) == log.Desire.none
  sm = FakeSM(_cs(v_ego=0.2, right=True), _cc(), nav=nav)
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.turnRight


def test_steer_fault_and_stale_carstate_block():
  intent = _intent(force=True)
  cs = _cs(v_ego=5.0, right=True)
  cs.steerFaultTemporary = True
  assert intent.select(FakeSM(cs, _cc()), 1, log.Desire.none) == log.Desire.none
  sm = FakeSM(_cs(v_ego=5.0, right=True), _cc())
  sm.valid["carState"] = False
  assert intent.select(sm, 2, log.Desire.none) == log.Desire.none


def test_observe_gated_and_evidence_expiry():
  intent = _intent(force=True, model_confirm=False)
  v = 25.0 * CV.MPH_TO_MS
  cs = _cs(v_ego=v, right=True, a_ego=-1.0)
  sm = FakeSM(cs, _cc())
  assert not intent.observe(sm, _model(), model_ns=1, now_ns=1)
  assert not intent.signal_model.ready

  intent = _intent(force=True, model_confirm=True)
  ev = intent.signal_model
  ev.observe(cs, _cc(), _model(), model_ns=1_000_000, now_ns=1_000_000, plan=_plan(False))
  ev.observe(cs, _cc(), _model(), model_ns=1_000_000 + CONFIRM_NS, now_ns=1_000_000 + CONFIRM_NS, plan=_plan(False))
  now = 1_000_000 + CONFIRM_NS
  assert ev.ready
  assert ev.current(cs, _cc(), _plan(False), now_ns=now)
  assert not ev.current(cs, _cc(), _plan(False), now_ns=now + MAX_AGE_NS + 1)
  # model shouldStop resets evidence
  ev.observe(cs, _cc(), _model(should_stop=True), model_ns=now, now_ns=now, plan=_plan(False))
  assert not ev.ready
