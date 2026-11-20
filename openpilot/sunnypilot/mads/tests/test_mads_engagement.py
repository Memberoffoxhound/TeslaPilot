from openpilot.cereal import custom, log
from opendbc.car import structs
from opendbc.sunnypilot.structs import CarParamsSP
from openpilot.conftest import FakeParams
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.selfdrive.selfdrived.state import StateMachine
from openpilot.sunnypilot.mads.mads import ModularAssistiveDrivingSystem
from openpilot.sunnypilot.selfdrive.selfdrived.events import EventsSP

EventName = log.OnroadEvent.EventName
EventNameSP = custom.OnroadEventSP.EventName
ButtonType = structs.CarState.ButtonEvent.Type


class FakeSelfdrive:
  def __init__(self, brand, mads_on, steering_mode=0):
    self.CP = structs.CarParams(brand=brand)
    self.CP_SP = CarParamsSP()
    self.params = FakeParams({"Mads": mads_on, "MadsMainCruiseAllowed": True, "MadsSteeringMode": steering_mode,
                              "MadsUnifiedEngagementMode": True})
    self.events = Events()
    self.events_sp = EventsSP()
    self.state_machine = StateMachine()
    self.enabled = self.active = False
    self.initialized = True
    self.CS_prev = structs.CarState()
    self.sm = {'pandaStates': []}
    self.disengage_on_accelerator = False
    self.mads = ModularAssistiveDrivingSystem(self)

  # selfdrived order: openpilot state machine first, then MADS
  def step(self, CS, events=()):
    self.events.clear()
    self.events_sp.clear()
    for e in events:
      self.events.add(e)
    self.enabled, self.active = self.state_machine.update(self.events)
    self.mads.update(CS)
    self.CS_prev = CS

  # controlsd: lateral follows MADS when the toggle is on
  @property
  def lat_active(self):
    return self.mads.active if self.mads.enabled_toggle else self.active


def car_state(available=True, buttons=(), brake=False, gas=False):
  CS = structs.CarState(brakePressed=brake, gasPressed=gas)
  CS.cruiseState.available = available
  CS.buttonEvents = [structs.CarState.ButtonEvent(pressed=True, type=b) for b in buttons]
  return CS


def engage(sd):
  sd.step(car_state())
  sd.step(car_state(), [EventName.pcmEnable])
  assert sd.enabled and sd.lat_active


class TestTeslaCancel:
  def test_cancel_keeps_lateral_with_tits(self):
    sd = FakeSelfdrive("tesla", mads_on=True, steering_mode=2)
    engage(sd)
    sd.step(car_state(buttons=(ButtonType.cancel,)), [EventName.buttonCancel])
    assert not sd.enabled
    assert sd.lat_active
    assert sd.events_sp.has(EventNameSP.manualLongitudinalRequired)

  def test_cancel_disengages_all_without_tits(self):
    sd = FakeSelfdrive("tesla", mads_on=False)
    engage(sd)
    sd.step(car_state(buttons=(ButtonType.cancel,)), [EventName.buttonCancel])
    assert not sd.enabled
    assert not sd.lat_active

  def test_brake_disengages_all_with_tits(self):
    sd = FakeSelfdrive("tesla", mads_on=True, steering_mode=2)
    engage(sd)
    sd.step(car_state(brake=True), [EventName.pedalPressed])
    assert not sd.enabled
    assert not sd.lat_active


class TestMainCruiseOff:
  def test_lkas_button_blocked_with_main_off(self):
    sd = FakeSelfdrive("toyota", mads_on=True)
    sd.step(car_state(available=False))
    sd.step(car_state(available=False, buttons=(ButtonType.lkas,)))
    assert not sd.mads.enabled

  def test_lkas_button_engages_with_main_on(self):
    sd = FakeSelfdrive("toyota", mads_on=True)
    sd.CS_prev.cruiseState.available = True
    sd.step(car_state(buttons=(ButtonType.lkas,)))
    assert sd.mads.enabled and sd.lat_active

  def test_main_on_engages_lateral(self):
    sd = FakeSelfdrive("toyota", mads_on=True)
    sd.step(car_state(available=False))
    sd.step(car_state())
    assert sd.mads.enabled and sd.lat_active

  def test_main_off_disengages_lateral(self):
    sd = FakeSelfdrive("toyota", mads_on=True)
    sd.step(car_state())
    sd.step(car_state(buttons=(ButtonType.lkas,)))
    sd.step(car_state(available=False))
    assert not sd.mads.enabled and not sd.lat_active

  def test_button_enable_removed_with_main_off(self):
    sd = FakeSelfdrive("toyota", mads_on=True)
    sd.step(car_state(available=False))
    sd.step(car_state(available=False), [EventName.buttonEnable])
    assert not sd.mads.enabled
    assert not sd.events.has(EventName.buttonEnable)


class TestBrakeAllModes:
  # brake always ends longitudinal and release never brings it back; lateral follows the TITS on brake option
  def _brake(self, mode):
    sd = FakeSelfdrive("toyota", mads_on=True, steering_mode=mode)
    engage(sd)
    sd.step(car_state(brake=True), [EventName.pedalPressed])
    pressed = (sd.enabled, sd.lat_active)
    for _ in range(3):
      sd.step(car_state())
    return pressed, (sd.enabled, sd.lat_active)

  def test_keep(self):
    assert self._brake(0) == ((False, True), (False, True))

  def test_pause(self):
    assert self._brake(1) == ((False, False), (False, True))

  def test_disengage(self):
    assert self._brake(2) == ((False, False), (False, False))


def test_disengage_on_accelerator_follows_selfdrive():
  sd = FakeSelfdrive("toyota", mads_on=True)
  sd.CS_prev.gasPressed = False
  CS = car_state(gas=True)
  sd.events.add(EventName.pedalPressed)
  sd.disengage_on_accelerator = True
  assert not sd.mads.pedal_pressed_non_gas_pressed(CS)
  sd.disengage_on_accelerator = False
  assert sd.mads.pedal_pressed_non_gas_pressed(CS)
