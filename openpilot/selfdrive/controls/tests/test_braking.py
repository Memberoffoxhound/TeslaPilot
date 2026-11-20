from openpilot.conftest import FakeParams
from openpilot.selfdrive.controls.lib.cruise_braking import (
  A_CRUISE_MIN, A_CRUISE_MIN_SOFT, braking_visible, clamp_cruise_min, cruise_min_from_params)


def test_default_unset_params_are_firm():
  assert cruise_min_from_params(FakeParams()) == A_CRUISE_MIN == -1.2


def test_firm_and_soft_reach_the_planner():
  firm = FakeParams(BrakingFirm=True)
  soft = FakeParams(BrakingFirm=False)
  assert cruise_min_from_params(firm) == A_CRUISE_MIN == -1.2
  assert cruise_min_from_params(soft) == A_CRUISE_MIN_SOFT == -0.5
  # the planner stores clamp_cruise_min(cruise_min_from_params(params))
  assert clamp_cruise_min(cruise_min_from_params(firm)) == -1.2
  assert clamp_cruise_min(cruise_min_from_params(soft)) == -0.5
  firm.put("BrakingFirm", False)
  assert clamp_cruise_min(cruise_min_from_params(firm)) == -0.5


def test_cruise_min_never_below_firm_floor():
  assert clamp_cruise_min(-2.0) == A_CRUISE_MIN
  assert clamp_cruise_min(-1.2) == A_CRUISE_MIN
  assert clamp_cruise_min(-0.5) == -0.5


def test_braking_toggle_hidden_without_longitudinal():
  assert braking_visible(True) is True
  assert braking_visible(False) is False
