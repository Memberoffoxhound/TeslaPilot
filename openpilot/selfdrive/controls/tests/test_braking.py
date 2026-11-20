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


def test_unknown_key_defaults_to_firm():
  from openpilot.common.params import UnknownKeyName
  class Boom:
    def get(self, *a, **k):
      raise UnknownKeyName(b"BrakingFirm")
  assert cruise_min_from_params(Boom()) == A_CRUISE_MIN == -1.2


def _planner_cls():
  import sys
  try:
    from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner, get_cruise_accel
    return LongitudinalPlanner, get_cruise_accel
  except ModuleNotFoundError:
    import types
    sys.modules.pop("openpilot.selfdrive.controls.lib.longitudinal_planner", None)
    name = "openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc"
    if name not in sys.modules:
      m = types.ModuleType(name)
      class LongitudinalMpc:
        def __init__(self, *a, **k):
          pass
      m.LongitudinalMpc = LongitudinalMpc
      m.LongitudinalPlanSource = types.SimpleNamespace(cruise="cruise")
      m.T_IDXS = [0.0]
      sys.modules[name] = m
    from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner, get_cruise_accel
    return LongitudinalPlanner, get_cruise_accel


def test_planner_clamps_and_follows_param_cadence(params_root):
  from types import SimpleNamespace
  from openpilot.common.realtime import DT_MDL
  from openpilot.selfdrive.controls.lib.set_speed_assist import PARAMS_UPDATE_PERIOD
  LongitudinalPlanner, get_cruise_accel = _planner_cls()
  params = FakeParams(BrakingFirm=True)
  planner = LongitudinalPlanner(SimpleNamespace(openpilotLongitudinalControl=True), params=params)
  assert planner.a_cruise_min == A_CRUISE_MIN == -1.2
  assert get_cruise_accel(0.0, 30.0, 0.0, 0.0, planner.dt, a_cruise_min=-2.0) >= A_CRUISE_MIN
  planner.update_params()
  params.put("BrakingFirm", False)
  period = int(PARAMS_UPDATE_PERIOD / planner.dt)
  assert period == int(PARAMS_UPDATE_PERIOD / DT_MDL)
  for _ in range(period - 1):
    planner.update_params()
    assert planner.a_cruise_min == A_CRUISE_MIN
  planner.update_params()
  assert planner.a_cruise_min == A_CRUISE_MIN_SOFT == -0.5
  assert get_cruise_accel(0.0, 30.0, 0.0, 0.0, planner.dt, a_cruise_min=planner.a_cruise_min) >= A_CRUISE_MIN
