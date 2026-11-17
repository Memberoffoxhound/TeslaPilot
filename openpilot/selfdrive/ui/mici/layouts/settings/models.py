# Settings -> models: zoompilot's mici models panel on Highland widgets. Logic: model_picker.py, accelerator_link.py.
from openpilot.selfdrive.ui import accelerator_link as al
from openpilot.selfdrive.ui import model_picker as mp
from openpilot.selfdrive.ui.mici.layouts.settings.model_widgets import CurrentModelInfo, JetlinkIosToggle
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import SettingDescriptionDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller


JETLINK_DESC = ("Picks the big model Jetlink runs on the phone or computer.\n" +
                "The phone downloads and builds it; the small model drives until it is ready.")
CHESTNUT_DESC = ("Picks the big model the chestnut runs.\n" +
                 "Others compile on the chestnut while parked; the comma big model drives until one is ready.")
TITLES = {'chestnut': ("chestnut big model", CHESTNUT_DESC), 'jetlink': ("jetlink big model", JETLINK_DESC)}


def _offroad() -> bool:
  return not ui_state.started


def _bundled_progress() -> dict | None:
  # the first-boot pull of the comma big model reads as progress, not "unavailable"
  p = getattr(ui_state, 'accel_progress', None)
  if mp.mode() == 'chestnut' and p is not None and p[0] == 'download':
    return {'stage': 'downloading', 'frac': p[1] or 0.0}
  return None


class ModelsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._info = CurrentModelInfo(*self._model_info())
    self._small = GreyBigButton("small model", mp.SMALL_MODEL)
    self._small_note = GreyBigButton("", mp.SMALL_NOTE)
    self._big = BigButton("jetlink big model", mp.big_model_label(), description=JETLINK_DESC)
    self._big.set_click_callback(self._show_folders)
    self._big.set_enabled(_offroad)
    # locked onroad: jetlink switches the link only when parked
    self._link = JetlinkIosToggle()
    self._link.set_enabled(_offroad)
    self._refresh = BigButton("refresh models", mp.list_label(), description="Fetches the latest list of big models.")
    self._refresh.set_click_callback(mp.refresh)
    self._refresh.set_enabled(_offroad)
    self._reset = BigButton("reset to default", "", description="Goes back to the default big model.")
    self._reset.set_click_callback(mp.reset_to_default)
    self._reset.set_enabled(lambda: _offroad() and mp.picked() is not None)
    self._scroller.add_widgets([self._info, self._big, self._link, self._refresh, self._reset, self._small, self._small_note])
    self._tick = 0
    self._mode = ''

  @staticmethod
  def _set(btn, value):
    value = value or "-"
    if btn.get_value() != value:
      btn.set_value(value)

  def _push(self, items):
    scroller = NavScroller()
    scroller._scroller.add_widgets(items)
    gui_app.push_widget(scroller)

  def _show_folders(self):
    try:
      folders = mp.folders()
      default = BigButton(f"{mp.default_name()} ({mp.DEFAULT_LABEL})".lower())
      default.set_click_callback(self._pick_default)
      items = [default]
      if not folders:
        items.append(GreyBigButton("no models yet", "connect to the internet and refresh models"))
      for folder, bundles in folders:
        btn = BigButton(folder.lower(), f"{len(bundles)} models")
        btn.set_click_callback(lambda b=bundles: self._show_models(b))
        items.append(btn)
      self._push(items)
    except Exception:
      pass

  def _show_models(self, bundles):
    try:
      items = []
      for b in bundles:
        btn = BigButton(mp.short_name(b["display_name"]).lower(), mp.model_note(b["ref"]))
        btn.set_click_callback(lambda ref=b["ref"]: self._pick(ref))
        items.append(btn)
      self._push(items)
    except Exception:
      pass

  def _pick(self, ref):
    try:
      mp.select(ref)
    finally:
      gui_app.pop_widgets_to(self)

  def _pick_default(self):
    try:
      mp.reset_to_default()
    finally:
      gui_app.pop_widgets_to(self)

  @staticmethod
  def _model_info() -> tuple[str, str, str]:
    try:
      return al.model_info(ui_state.jetlink, ui_state.chestnut_state.value, ui_state.chestnut_present,
                           mp.SMALL_MODEL, mp.big_model_label(), mp.compile_progress() or _bundled_progress())
    except Exception:
      return mp.SMALL_MODEL, "big model", "-"

  def show_event(self):
    super().show_event()
    self._tick = 0
    self._link.refresh()
    self._apply_mode()

  def _apply_mode(self):
    # only what the fitted accelerator uses: no picker without one, no iPhone toggle on a chestnut
    mode = mp.mode()
    for w in (self._big, self._refresh, self._reset):
      w.set_visible(mode != 'none')
    self._link.set_visible(mode != 'chestnut')
    if mode in TITLES and self._mode != mode:
      title, desc = TITLES[mode]
      self._big.set_text(title)
      self._big.set_long_press_callback(lambda: gui_app.push_widget(SettingDescriptionDialog(title, desc)))
    self._mode = mode

  def _update_state(self):
    super()._update_state()
    self._tick += 1
    if self._tick % 15 != 1:  # params reads a few times a second, not every frame
      return
    try:
      self._set(self._big, mp.big_model_label() + (" (queued)" if mp.queued() else ""))
      self._set(self._refresh, mp.list_label())
      self._info.set_info(*self._model_info())
      self._link.refresh()
      self._apply_mode()
    except Exception:
      pass
