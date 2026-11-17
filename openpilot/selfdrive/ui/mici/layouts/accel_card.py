# one-time card when a chestnut or Jetlink is first seen offroad; none on unplug
import time

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app

DEVICE, ACK = "AcceleratorDevice", "AcceleratorAck"
MODEL_LINE = "You can see progress and change your model in Settings, Models."
CARDS = {
  'chestnut': ("Chestnut connected", "Settings have been updated to manage your chestnut."),
  'jetlink': ("Jetlink connected", "Settings have been updated to manage Jetlink."),
}
BIG_READY = "The comma big model is ready."
BIG_DOWNLOADING = "The comma big model downloads the first time. The chestnut icon fills as it downloads."


def card(mode: str, big_model_ready: bool = True) -> tuple[str, list[str]] | None:
  # pages after the title card
  if mode not in CARDS:
    return None
  title, first = CARDS[mode]
  pages = [first] + ([BIG_READY if big_model_ready else BIG_DOWNLOADING] if mode == 'chestnut' else []) + [MODEL_LINE]
  return title, pages


def due(params) -> str | None:
  # the mode to announce; an unplug is acked quietly
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
      title, pages = card(mode, chestnut_compiled())
      # a card per sentence: two don't fit on one; the dialog's own info icon, not a warning
      self.page = SettingDescriptionDialog(title, "\n".join(pages).replace(". ", ".\n"))
      self.page._scroller.items[0].set_value("settings updated")
      gui_app.push_widget(self.page)
    return self.active
