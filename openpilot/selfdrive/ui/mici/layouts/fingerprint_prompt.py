"""Learn a Tesla EPS reply from an unrecognized, passive drive."""
from opendbc.car.tesla.fingerprint_overlay import catalog
from openpilot.selfdrive.car.local_fingerprints import save
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import wire_confirm
from openpilot.selfdrive.ui.ui_state import ui_state


class FingerprintPrompt:
  def __init__(self, parent):
    self.parent, self.page, self.asked = parent, None, False

  @property
  def active(self):
    return self.page is not None and gui_app.widget_in_stack(self.page)

  def tick(self):
    ui = ui_state
    if not ui.ignition:
      self.asked = False
    cp = ui.sm["carParams"]
    eligible = ui.started and cp.brand == "mock" and ui.sm.recv_frame["carParams"] > ui.started_frame
    if self.active and not eligible:
      gui_app.pop_widgets_to(self.parent, instant=True)
      self.page = None
    if eligible and not self.asked:
      self.asked = True
      self.cp = cp.as_builder()
      self.page = self._show("Are you on a Tesla?", [("Yes", self._pick), ("No", self._no)])
    return self.active

  def _show(self, title, choices):
    page = NavScroller()
    items = [GreyBigButton(title, "Controls unavailable. Keep the vehicle in Park.")]
    for text, callback in choices:
      button = BigButton(text)
      button.set_click_callback(callback)
      items.append(button)
    page._scroller.add_widgets(items)
    gui_app.push_widget(page)
    return page

  def _no(self):
    gui_app.pop_widgets_to(self.parent, instant=True)
    self.page = alert_dialog("Sorry, we couldn’t identify your car.")
    gui_app.push_widget(self.page)

  def _pick(self):
    self._show("Choose year and model", [(f"{year} {model}", lambda p=platform, y=year, m=model: self._review(p, y, m))
                                        for year, platform, model in catalog()])

  def _review(self, platform, year, model):
    self._show(f"{year} Tesla {model}", [("This is my car", lambda: self._confirm(platform, model))])

  def _confirm(self, platform, model):
    page = NavScroller()
    wire_confirm(page, "confirm vehicle", ["Verify the year, model and Autopilot computer on your car's screen.",
                                         "A wrong fingerprint can configure the wrong controls.",
                                         "Save the captured EPS firmware locally, then restart to apply."],
                  lambda: self._save(platform, model), label="slide to\nsave")
    gui_app.push_widget(page)

  def _save(self, platform, model):
    if not ui_state.started or ui_state.sm["carParams"].brand != "mock":
      return
    try:
      save(platform, self.cp.carFw)
    except (OSError, ValueError) as e:
      gui_app.pop_widgets_to(self.parent, instant=True)
      self.page = alert_dialog(str(e))
      gui_app.push_widget(self.page)
      return
    gui_app.pop_widgets_to(self.parent, instant=True)
    self.page = ConfirmDialog("Fingerprint saved. Please wait in Park until the device restarts and goes onroad so your "
                              + f"Tesla {model} stays happy. Fingerprint sharing is coming later.",
                              "Restart to apply", callback=self._restart)
    gui_app.push_widget(self.page)

  @staticmethod
  def _restart(result):
    if result == DialogResult.CONFIRM and not ui_state.engaged:
      ui_state.params.put_bool("DoReboot", True)
