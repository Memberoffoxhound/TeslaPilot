from collections.abc import Callable

from openpilot.cereal import log
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle, BigToggle, BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import SettingDescriptionDialog, wire_confirm
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.selfdrive.ui.layouts.settings.common import (
  lane_color_label, next_lane_color,
  onroad_ui_label, next_onroad_ui, restart_needed_callback,
  compass_size_label, next_compass_size,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.car import tesla_step_aside, park_offroad
from openpilot.selfdrive.ui import tripstats
from openpilot.selfdrive.ui.mici.layouts.settings.initial_cruise_speed import InitialCruiseSpeedButton
from openpilot.selfdrive.ui import mads

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants
TITS_CARD_FONT = 30


class AutoLaneChangeConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()
    wire_confirm(self, "enabling\nauto lane change", [
      "Auto Lane Change uses Tesla's stock blind spot monitoring",
      "to check for a vehicle in the adjacent lane prior to merging.",
      "You are still responsible for ensuring the lane of travel is clear",
      "and agree to intervene as necessary.",
    ], on_confirm)


class ParkOffroadConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()
    wire_confirm(self, "enabling\ngo offroad in park", [
      "Tesla: TeslaPilot goes offroad after Park is held 3 s.",
      "Only D or R brings it back onroad, as a new route. The car staying on does not.",
      "Ignition starts TeslaPilot as before. Turning the car off and on resets it.",
      "Every Park splits the route. After D/R, TeslaPilot needs several seconds to be ready.",
      "Parked offroad with the car on, uploads and updates run as offroad.",
      "The shutdown timer starts only once the car powers off.",
      "Summon and Autopark keep it offroad, relay open. FSD from Park goes through step aside.",
      "Also turns on the drive summary card.",
    ], on_confirm)


class _TitsTitleCard(GreyBigButton):
  # the expansion with the ASS line under it, smaller to fit one card
  def __init__(self, title: str, under: str):
    super().__init__(title, under)
    self._label.set_font_size(TITS_CARD_FONT)
    self._sub_label.set_font_size(TITS_CARD_FONT)

  def _get_label_font_size(self):
    return TITS_CARD_FONT


class TitsConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None], brand: str | None = None):
    super().__init__()
    cards = mads.welcome_cards(brand)
    title, under = cards[0]
    wire_confirm(self, "enabling\nTITS", [_TitsTitleCard(title, under), *cards[1:]], on_confirm)


class _ParamCycle(BigButton):
  def __init__(self, title: str, key: str, label_fn, next_fn):
    super().__init__(title, "")
    self._params = ui_state.params
    self._key = key
    self._label_fn = label_fn
    self._next_fn = next_fn
    self.refresh()

  def refresh(self):
    value = self._label_fn(self._params)
    if value != self.value:
      self.set_value(value)

  def show_event(self):
    super().show_event()
    self.refresh()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    self._params.put(self._key, self._next_fn(self._params), block=True)
    self.refresh()


class ThemeLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._scroller.add_widgets([
      _ParamCycle("onroad UI", "CustomOnroadUi", onroad_ui_label, next_onroad_ui),
      _ParamCycle("compass size", "CompassSize", compass_size_label, next_compass_size),
      _ParamCycle("theme", "LaneColor", lane_color_label, next_lane_color),
    ])


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._personality_toggle = BigMultiParamToggle("driving personality", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"],
                                                   description="Standard is recommended.\n" +
                                                               "Aggressive follows closer, with firmer gas and braking.\n" +
                                                               "Relaxed leaves more space.\n" +
                                                               "Use the steering wheel distance button on supported cars.")
    # Based on rav4kumar's implementation of Automatic Lane Change (sunnypilot).
    self._alc_btn = BigToggle("auto lane change", initial_state=ui_state.params.get_bool("AutoLaneChangeEnabled"),
                             toggle_callback=self._on_alc)
    # Set Speed Assist, from sunnypilot (zephleggett). Only with openpilot longitudinal.
    self._ssa_toggle = BigParamControl("set speed assist", "SetSpeedAssist",
                                       description="Accelerate up to the set speed, or the following distance behind a lead,\n" +
                                                   "when the driving model would drive slower. The model still decides when to slow down.\n" +
                                                   "Needs openpilot longitudinal control.")
    self._ssa_toggle.set_enabled(lambda: ui_state.has_longitudinal_control)
    self._initial_cruise_speed = InitialCruiseSpeedButton()

    # TITS (MADS), changes only offroad; sub-options only for the car's brand
    self._tits_btn = BigToggle("TITS", initial_state=ui_state.params.get_bool("Mads"), toggle_callback=self._on_tits,
                               description=mads.toggle_description(None))
    # Tesla adds the brake note, so read the brand when the description opens
    self._tits_btn.set_long_press_callback(lambda: gui_app.push_widget(SettingDescriptionDialog("TITS", mads.toggle_description(self._brand()))))
    self._tits_main_cruise = BigParamControl("TITS with main cruise", mads.MAIN_CRUISE,
                                             description="Turning main cruise on also turns TITS on.\n" +
                                                         "Without a TITS button on the wheel, turning this off keeps TITS from engaging.")
    self._tits_unified = BigParamControl("TITS with cruise", mads.UNIFIED,
                                         description="Engaging cruise also engages TITS.\n" +
                                                     "TITS then stays on until you turn it off with its button or turn the car off.")
    self._tits_brake = BigMultiParamToggle("TITS on brake", mads.STEERING_MODE, mads.STEERING_MODES,
                                           description="Remain active: TITS keeps steering while you brake.\n" +
                                                       "Pause: TITS pauses while you brake and resumes after.\n" +
                                                       "Disengage: braking turns TITS off.")
    self._tits_screen = BigMultiParamToggle("TITS screen button", mads.SCREEN_BUTTON, mads.SCREEN_BUTTONS,
                                            select_callback=lambda _: self._refresh_tits(),
                                            description="Touch the Tesla screen with this many fingers to turn TITS on or off.")
    self._tits_visible: set[str] = set()
    for key, w in ((mads.MAIN_CRUISE, self._tits_main_cruise), (mads.UNIFIED, self._tits_unified),
                   (mads.STEERING_MODE, self._tits_brake), (mads.SCREEN_BUTTON, self._tits_screen)):
      w.set_visible(lambda k=key: ui_state.tits_enabled and k in self._tits_visible)
    for w in (self._tits_btn, self._tits_main_cruise, self._tits_unified, self._tits_brake, self._tits_screen):
      w.set_enabled(lambda: not ui_state.started)
    self._initial_cruise_speed.set_visible(lambda: ui_state.CP is not None and ui_state.has_longitudinal_control and not ui_state.CP.pcmCruise)
    is_metric_toggle = BigToggle("use metric units", initial_state=ui_state.params.get_bool("IsMetric"), toggle_callback=self._on_metric_toggle)
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled",
                                 description="Warn when you drift across a detected lane line.\n" +
                                             "Only above 31 mph (50 km/h), with no turn signal.")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM", description="Monitor the driver even when openpilot is not engaged.")
    record_front = BigParamControl("record & upload cabin camera", "RecordFront",
                                   description_icon=gui_app.texture("icons_mici/settings/device/cameras.png", 64, 64),
                                   toggle_callback=restart_needed_callback, description="Upload cabin camera data to help improve driver monitoring.")
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", description_icon=gui_app.texture("icons_mici/microphone.png", 64, 64),
                                 toggle_callback=restart_needed_callback,
                                 description="Record microphone audio while driving.\n" +
                                             "Audio is included in dashcam videos in comma connect.")
    enable_openpilot = BigParamControl("enable TeslaPilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback,
                                       description="Enable to use TeslaPilot driver assistance.\n" +
                                                   "Disable to use your car's stock driver assistance.")

    # Tesla step aside, default on
    self._step_aside_btn = BigToggle("step aside for tesla fsd", initial_state=tesla_step_aside.enabled(ui_state.params),
                                     toggle_callback=self._on_step_aside,
                                     description="When Tesla Autosteer or FSD is selected or driving (or Summon),\n" +
                                                 "TeslaPilot steps aside: relay open, nothing sent,\n" +
                                                 "screen off after a 5 s alert. Back when Tesla is on TACC.")
    self._step_aside_btn.set_enabled(lambda: not ui_state.engaged)

    # park offroad and drive summary share one toggle
    self._park_offroad_btn = BigToggle("go offroad in park", initial_state=park_offroad.enabled(ui_state.params),
                                       toggle_callback=self._on_park_offroad,
                                       description="Offroad after Park is held 3 s, back onroad on D/R.\n" +
                                                   "Adds the drive summary card.")

    self._scroller.add_widgets([
      self._alc_btn,
      self._personality_toggle,
      self._ssa_toggle,
      self._initial_cruise_speed,
      self._tits_btn,
      self._tits_main_cruise,
      self._tits_unified,
      self._tits_brake,
      self._tits_screen,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      record_front,
      record_mic,
      self._step_aside_btn,
      self._park_offroad_btn,
      enable_openpilot,
    ])

    # Toggle lists
    self._refresh_toggles = (
      ("AutoLaneChangeEnabled", self._alc_btn),
      ("SetSpeedAssist", self._ssa_toggle),
      ("Mads", self._tits_btn),
      (mads.MAIN_CRUISE, self._tits_main_cruise),
      (mads.UNIFIED, self._tits_unified),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
    )

    enable_openpilot.set_enabled(lambda: not ui_state.engaged)
    always_on_dm_toggle.set_enabled(not ui_state.params.get_bool("AlwaysOnDMLock"))
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic.set_enabled(lambda: not ui_state.engaged)

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def scroll_to_set_speed_assist(self):
    self._scroller._layout()
    w = self._ssa_toggle
    self._scroller.scroll_to((w.rect.x + w.rect.width / 2) - (self._rect.x + self._rect.width / 2), smooth=True)

  def scroll_to_tits(self):
    self._scroller._layout()
    w = self._tits_btn
    self._scroller.scroll_to((w.rect.x + w.rect.width / 2) - (self._rect.x + self._rect.width / 2), smooth=True)
    w.trigger_grow_animation()

  @staticmethod
  def _brand() -> str | None:
    return ui_state.CP.brand if ui_state.CP is not None else None

  def _refresh_tits(self):
    brand = self._brand()
    car_flags = ui_state.CP.flags if ui_state.CP is not None else 0
    fingerprint = ui_state.CP.carFingerprint if ui_state.CP is not None else ""
    screen_button = mads.SCREEN_BUTTONS.index(self._tits_screen.value)
    self._tits_visible = mads.visible_options(brand, ui_state.cp_sp_flags, screen_button, car_flags, fingerprint)

  def _on_tits(self, state: bool):
    if state:
      self._tits_btn.set_checked(False)

      def on_confirm():
        ui_state.params.put_bool("Mads", True, block=True)
        self._tits_btn.set_checked(True)
        self._update_toggles()

      gui_app.push_widget(TitsConfirmPage(on_confirm, self._brand()))
    else:
      ui_state.params.put_bool("Mads", False, block=True)
      self._update_toggles()

  def _on_metric_toggle(self, state: bool):
    ui_state.params.put_bool("IsMetric", state, block=True)
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()
    self._initial_cruise_speed.refresh()

    if ui_state.CP is not None:
      self._personality_toggle.set_visible(ui_state.has_longitudinal_control)
    self._ssa_toggle.set_value("" if ui_state.has_longitudinal_control else "needs op long")

    self._tits_brake._load_value()
    self._tits_screen._load_value()
    self._refresh_tits()

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
    self._step_aside_btn.set_checked(tesla_step_aside.enabled(ui_state.params))
    self._park_offroad_btn.set_checked(park_offroad.enabled(ui_state.params))

  def _on_step_aside(self, state: bool):
    tesla_step_aside.put_bool(ui_state.params, tesla_step_aside.PARAM_ENABLED, state, block=True)
    restart_needed_callback()

  def _on_park_offroad(self, state: bool):
    def apply(on: bool):
      park_offroad.put_bool(ui_state.params, park_offroad.PARAM_ENABLED, on, block=True)
      tripstats.set_enabled(ui_state.params, on)  # the summary rides on the same toggle
      self._park_offroad_btn.set_checked(on)

    if state:
      self._park_offroad_btn.set_checked(False)
      gui_app.push_widget(ParkOffroadConfirmPage(lambda: apply(True)))
    else:
      apply(False)

  def _on_alc(self, state: bool):
    if state:
      self._alc_btn.set_checked(False)

      def on_confirm():
        ui_state.params.put_bool("AutoLaneChangeEnabled", True, block=True)
        self._alc_btn.set_checked(True)

      gui_app.push_widget(AutoLaneChangeConfirmPage(on_confirm))
    else:
      ui_state.params.put_bool("AutoLaneChangeEnabled", False, block=True)
