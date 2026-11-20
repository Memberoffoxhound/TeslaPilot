# MADS events, ported from sunnypilot, see LICENSE.sunnypilot.
import bisect

from openpilot.cereal import custom, log
from opendbc.car.structs import car
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.events import Alert, AlertCallbackType, EngagementAlert, Events, ET, ImmediateDisableAlert, \
  NoEntryAlert, Priority, wrong_car_mode_alert

AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = log.SelfdriveState.AudibleAlert
EventNameSP = custom.OnroadEventSP.EventName

EVENT_NAME_SP = {v: k for k, v in EventNameSP.schema.enumerants.items()}


class EventsSP(Events):
  def __init__(self):
    super().__init__()
    self.event_counters = dict.fromkeys(EVENTS_SP.keys(), 0)

  def contains(self, event_type: str) -> bool:
    return any(event_type in EVENTS_SP.get(e, {}) for e in self.events)

  def create_alerts(self, event_types: list[str], callback_args=None):
    if callback_args is None:
      callback_args = []

    ret = []
    for e in self.events:
      types = EVENTS_SP[e].keys()
      for et in event_types:
        if et in types:
          alert = EVENTS_SP[e][et]
          if not isinstance(alert, Alert):
            alert = alert(*callback_args)

          if DT_CTRL * (self.event_counters[e] + 1) >= alert.creation_delay:
            alert.alert_type = f"{EVENT_NAME_SP[e]}/{et}"
            alert.event_type = et
            ret.append(alert)
    return ret

  def add_from_msg(self, events):
    for e in events:
      bisect.insort(self.events, e.name.raw)

  def to_msg(self):
    ret = []
    for event_name in self.events:
      event = custom.OnroadEventSP.Event.new_message()
      event.name = event_name
      for event_type in EVENTS_SP.get(event_name, {}):
        setattr(event, event_type, True)
      ret.append(event)
    return ret


def silent_alert() -> Alert:
  return Alert("", "", AlertStatus.normal, AlertSize.none, Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.)


EVENTS_SP: dict[int, dict[str, Alert | AlertCallbackType]] = {
  EventNameSP.lkasEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventNameSP.lkasDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventNameSP.manualSteeringRequired: {
    ET.USER_DISABLE: Alert(
      "MADS is OFF",
      "Manual Steering Required",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.disengage, 1.),
  },

  EventNameSP.manualLongitudinalRequired: {
    ET.WARNING: Alert(
      "Cruise Control: OFF",
      "Manual Speed Control Required",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventNameSP.silentLkasEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.none),
  },

  EventNameSP.silentLkasDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
  },

  EventNameSP.silentBrakeHold: {
    ET.WARNING: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert("Brake Hold Active"),
  },

  EventNameSP.silentWrongGear: {
    ET.WARNING: silent_alert(),
    ET.NO_ENTRY: Alert(
      "Gear not D",
      "openpilot Unavailable",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0.),
  },

  EventNameSP.silentReverseGear: {
    ET.PERMANENT: Alert(
      "Reverse\nGear",
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    ET.NO_ENTRY: NoEntryAlert("Reverse Gear"),
  },

  EventNameSP.silentDoorOpen: {
    ET.WARNING: silent_alert(),
    ET.NO_ENTRY: NoEntryAlert("Door Open"),
  },

  EventNameSP.silentSeatbeltNotLatched: {
    ET.WARNING: silent_alert(),
    ET.NO_ENTRY: NoEntryAlert("Seatbelt Unlatched"),
  },

  EventNameSP.silentParkBrake: {
    ET.WARNING: silent_alert(),
    ET.NO_ENTRY: NoEntryAlert("Parking Brake Engaged"),
  },

  EventNameSP.controlsMismatchLateral: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Controls Mismatch: Lateral"),
    ET.NO_ENTRY: NoEntryAlert("Controls Mismatch: Lateral"),
  },

  EventNameSP.wrongCarModeAlertOnly: {
    ET.WARNING: wrong_car_mode_alert,
  },

  EventNameSP.pedalPressedAlertOnly: {
    ET.WARNING: NoEntryAlert("Pedal Pressed"),
  },
}
