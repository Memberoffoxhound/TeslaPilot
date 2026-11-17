# one-time card when a chestnut or Jetlink is first seen offroad; none on unplug
import time

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app

DEVICE, ACK = "AcceleratorDevice", "AcceleratorAck"
MODEL_LINE = "You can change your model in Settings, Models."
CARDS = {
  'chestnut': ("Chestnut connected", "Settings have been updated to manage your chestnut."),
  'jetlink': ("Jetlink connected", "Settings have been updated to manage Jetlink."),
}


def card(mode: str, big_model_ready: bool = True) -> tuple[str, str] | None:
  if mode not in CARDS:
    return None
  title, body = CARDS[mode]
  if mode == 'chestnut':
    body += " The comma big model is ready." if big_model_ready else " The comma big model is downloading."
  return title, f"{body} {MODEL_LINE}"


def due(params) -> str | None:
  """The mode to announce, after quietly acking an unplug."""
  mode = (params.get(DEVICE) or 'none').split('-')[0]
  if mode == (params.get(ACK) or 'none'):
    return None
  if mode not in CARDS:
    params.put(ACK, 'none')
    return None
  return mode


class AccelCard:
  def __init__(self, parent):
    self.parent, self.page, self._next = parent, None, 0.0

  @property
  def active(self):
    return self.page is not None and gui_app.widget_in_stack(self.page)

  def tick(self):
    if ui_state.started:
      if self.active:
        gui_app.pop_widgets_to(self.parent, instant=True)
      self.page = None
      return False
    if self.active or time.monotonic() < self._next:
      return self.active
    self._next = time.monotonic() + 1.0
    mode = due(ui_state.params)
    if mode:
      from openpilot.selfdrive.modeld.helpers import chestnut_compiled
      from openpilot.selfdrive.ui.mici.widgets.dialog import SettingDescriptionDialog
      ui_state.params.put(ACK, mode)
      title, body = card(mode, chestnut_compiled())
      self.page = SettingDescriptionDialog(title, body, gui_app.texture("icons_mici/offroad_alerts/orange_warning.png", 64, 64))
      self.page._scroller.items[0].set_value("settings updated")
      gui_app.push_widget(self.page)
    return self.active
