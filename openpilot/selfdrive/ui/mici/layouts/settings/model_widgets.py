# models panel Jetlink widgets, from zoompilot's mici models.py on Highland widgets.
import raylib_nb as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.accelerator_link import IOS_KEY
from openpilot.selfdrive.ui.mici.widgets.button import BigToggle
from openpilot.system.ui.lib.application import FontWeight
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel


class CurrentModelInfo(Widget):
  def __init__(self, active_text: str = "", info_header: str = "big model", info_text: str = ""):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 360, 180))
    header_color = rl.Color(255, 255, 255, int(255 * 0.9))
    subheader_color = rl.Color(255, 255, 255, int(255 * 0.9 * 0.65))
    max_width = int(self._rect.width - 20)
    self.current_model_header = UnifiedLabel("active model", 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    self.current_model_text = UnifiedLabel(active_text, 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN, scroll=True)
    self.info_header = UnifiedLabel(info_header, 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    self.info_text = UnifiedLabel(info_text, 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN, scroll=True)

  def set_info(self, active_text: str, info_header: str, info_text: str) -> None:
    self.current_model_text.set_text(active_text)
    self.info_header.set_text(info_header)
    self.info_text.set_text(info_text)

  def _render(self, _):
    self.current_model_header.set_position(self._rect.x + 20, self._rect.y - 10)
    self.current_model_header.render()
    self.current_model_text.set_position(self._rect.x + 20, self._rect.y + 68 - 25)
    self.current_model_text.render()
    self.info_header.set_position(self._rect.x + 20, self._rect.y + 114 - 30)
    self.info_header.render()
    self.info_text.set_position(self._rect.x + 20, self._rect.y + 161 - 25)
    self.info_text.render()


class JetlinkIosToggle(BigToggle):
  def __init__(self):
    super().__init__("jetlink over iPhone", toggle_callback=self._toggle,
                     description="Runs big models on an iPhone or iPad plugged into the comma.\n" +
                                 "A Jetson over USB is found on its own. Turn ADB off to use Jetlink.")
    self.refresh()

  def refresh(self) -> None:
    self.set_checked(Params().get_bool(IOS_KEY))

  def _toggle(self, checked: bool) -> None:
    try:
      Params().put_bool(IOS_KEY, checked, block=True)
    except Exception:
      pass
