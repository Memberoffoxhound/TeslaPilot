import pytest

from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.car.volkswagen.values import VolkswagenFlags
from opendbc.sunnypilot.structs import CarParamsSP
from opendbc.sunnypilot.car.tesla.values import TeslaFlagsSP
from openpilot.sunnypilot.mads.helpers import MadsSteeringModeOnBrake, mads_has_button, mads_main_reported, read_steering_mode_param, \
                                             set_car_specific_params

BUS = int(TeslaFlagsSP.HAS_VEHICLE_BUS)


class FakeParams:
  def __init__(self, **values):
    self.values = {"MadsSteeringMode": 0, "MadsUnifiedEngagementMode": False, "MadsMainCruiseAllowed": True, "TeslaMadsScreenButton": 0}
    self.values.update(values)

  def get(self, key, return_default=False, block=False):
    return self.values.get(key)

  def put(self, key, value, block=False):
    self.values[key] = value

  put_bool = put

  def remove(self, key):
    self.values.pop(key, None)


def car(brand, flags=0, sp_flags=0):
  CP = structs.CarParams(brand=brand, flags=flags)
  CP_SP = CarParamsSP()
  CP_SP.flags = sp_flags
  return CP, CP_SP


@pytest.mark.parametrize("sp_flags, screen", [(0, 0), (BUS, 0), (BUS, 1), (BUS, 3)])
def test_tesla_brake_always_disengages(sp_flags, screen):
  CP, CP_SP = car("tesla", sp_flags=sp_flags)
  params = FakeParams(TeslaMadsScreenButton=screen)
  assert read_steering_mode_param(CP, CP_SP, params) == MadsSteeringModeOnBrake.DISENGAGE
  set_car_specific_params(CP, CP_SP, params)
  assert params.values["MadsSteeringMode"] == 2
  assert "MadsMainCruiseAllowed" not in params.values


def test_brake_mode_kept_elsewhere():
  CP, CP_SP = car("toyota")
  assert read_steering_mode_param(CP, CP_SP, FakeParams(MadsSteeringMode=0)) == MadsSteeringModeOnBrake.REMAIN_ACTIVE


@pytest.mark.parametrize("brand, flags, main", [
  ("toyota", 0, True), ("volkswagen", 0, True), ("volkswagen", VolkswagenFlags.MLB, False),
  ("psa", 0, False), ("byd", 0, False), ("mg", 0, False), ("rivian", 0, False), ("tesla", 0, False), ("body", 0, False),
])
def test_main_reported(brand, flags, main):
  assert mads_main_reported(brand, flags) == main


def test_has_button():
  assert mads_has_button("ford") and mads_has_button("honda") and mads_has_button("chrysler") and mads_has_button("subaru")
  assert not mads_has_button("toyota") and not mads_has_button("hyundai")
  assert mads_has_button("hyundai", HyundaiFlags.HAS_LDA_BUTTON) and mads_has_button("hyundai", HyundaiFlags.CANFD)
  assert not mads_has_button("tesla", 0, BUS, 0) and mads_has_button("tesla", 0, BUS, 1) and not mads_has_button("tesla", 0, 0, 1)


@pytest.mark.parametrize("brand", ["psa", "byd", "mg"])
def test_cruise_only_brands_force_unified(brand):
  CP, CP_SP = car(brand)
  params = FakeParams()
  set_car_specific_params(CP, CP_SP, params)
  assert params.values["MadsUnifiedEngagementMode"] is True
  assert "MadsMainCruiseAllowed" not in params.values
  assert params.values["MadsSteeringMode"] == 0


def test_main_brand_untouched():
  CP, CP_SP = car("toyota")
  params = FakeParams()
  set_car_specific_params(CP, CP_SP, params)
  assert params.values == FakeParams().values
