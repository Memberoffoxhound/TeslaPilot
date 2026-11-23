# Ported from sunnypilot via zoompilot (421d151cf), see LICENSE.sunnypilot.
# Mici models panel on this fork's widgets: big models only, no driving options and no sunnylink favorites.
import time

import raylib_nb as rl

from openpilot.cereal import custom
from openpilot.selfdrive.jetlink_adapter import KEYS, MODES
from openpilot.selfdrive.ui.accelerator_link import big_model_note, big_model_progress, link_toggle_meaningful, standin_model
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiParamToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.model_info import (SMALL_MODEL, big_bundles, big_model_name, big_model_state, carrying_model,
                                               default_model_name,
                                               model_cache_size_mb, queued_name, refresh_in_progress, refresh_model_list)
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.sunnypilot.models.helpers import ACTIVE_BUNDLE_KEYS
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import NavScroller

LINK_MODE_LABELS = {"off": "off", "usb": "usb", "ios": "iOS"}
DS = custom.ModelManagerSP.DownloadStatus


def _model_info() -> tuple[str, str, str]:
  # (active model, info header, info text): the active line names what drives,
  # and a notable big-model state takes the info pair
  state = big_model_state()
  active_text = (carrying_model() or SMALL_MODEL).lower()
  provisioning = big_model_progress()
  if provisioning is not None:
    stage, frac, msg = provisioning
    if stage == 'failed':
      return active_text, "big model", msg or "unavailable"
    detail = msg or stage
    return active_text, "big model", f"{detail} {frac * 100:.0f}%" if frac > 0 else detail
  if standin := standin_model():
    return active_text, "big model", f"{standin.lower()} for now"
  if state == 'failed':
    return active_text, "big model", "not downloaded" if ui_state.chestnut_present and not ui_state.chestnut_compiled else "unavailable"
  if state == 'loading':
    return active_text, "big model", "getting ready"
  return active_text, "big model", big_model_name().lower()


class CurrentModelInfo(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 360, 180))
    header_color = rl.Color(255, 255, 255, int(255 * 0.9))
    subheader_color = rl.Color(255, 255, 255, int(255 * 0.9 * 0.65))
    max_width = int(self._rect.width - 20)
    active_text, info_header, info_text = _model_info()
    self.current_model_header = UnifiedLabel("active model", 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    self.current_model_text = UnifiedLabel(active_text, 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN, scroll=True)
    self.info_header = UnifiedLabel(info_header, 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    self.info_text = UnifiedLabel(info_text, 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN, scroll=True)

  def _render(self, _):
    self.current_model_header.set_position(self._rect.x + 20, self._rect.y - 10)
    self.current_model_header.render()
    self.current_model_text.set_position(self._rect.x + 20, self._rect.y + 68 - 25)
    self.current_model_text.render()
    self.info_header.set_position(self._rect.x + 20, self._rect.y + 114 - 30)
    self.info_header.render()
    self.info_text.set_position(self._rect.x + 20, self._rect.y + 161 - 25)
    self.info_text.render()


class ModelsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self.current_model_info = CurrentModelInfo()
    self._download_progress = "."
    self._download_frame = 0
    self._was_downloading = False

    self.select_model_btn = BigButton("select model", description="Choose the big driving model.\n" +
                                                                   "It runs on a Chestnut or over Jetlink; the built-in small model runs on the comma.")
    self.select_model_btn.set_click_callback(self._show_folders)

    self.refresh_btn = BigButton("refresh models", description="Fetches the latest list of big models.")
    self.refresh_btn.set_click_callback(self._refresh_models)
    self._refresh_start: float | None = None

    self.cancel_download_btn = BigButton("cancel download", description="Stops the model download in progress.")
    self.cancel_download_btn.set_click_callback(lambda: ui_state.params.remove("ModelManager_DownloadRef"))

    # follows the param; locked onroad like the model buttons: jetlink switches the link only parked
    self.link_toggle = BigMultiParamToggle("jetlink", KEYS.link, [LINK_MODE_LABELS[m] for m in MODES],
                                           description="Runs big models on a computer or phone plugged into the comma.\n" +
                                                       "USB for a Mac, Jetson, Linux PC or Android. iOS for an iPhone or iPad.\n" +
                                                       "Turns off ADB. The small model drives until the big model is ready.")
    self.link_toggle.set_enabled(lambda: ui_state.is_offroad())
    self.link_toggle.set_visible(link_toggle_meaningful())

    self.clear_cache_btn = BigButton("clear cache", value=f"{model_cache_size_mb():.1f} MB",
                                     description="Deletes downloaded models to free up space.\n" +
                                                 "Your selected big model is kept.")
    self.clear_cache_btn.set_click_callback(self._confirm_clear_cache)
    self._cache_size_time = 0.0

    self.main_items = [self.current_model_info, self.select_model_btn, self.cancel_download_btn, self.link_toggle,
                       self.refresh_btn, self.clear_cache_btn]
    self._scroller.add_widgets(self.main_items)

  @property
  def model_manager(self):
    return ui_state.sm["modelManagerSP"]

  @staticmethod
  def _get_grouped_bundles(bundles):
    folders: dict = {}
    for bundle in bundles:
      folder = next((override.value for override in bundle.overrides if override.key == "folder"), "")
      folders.setdefault(folder, []).append(bundle)
    return folders

  def _push_selection_view(self, items):
    scroller = NavScroller()
    scroller._scroller.add_widgets(items)
    gui_app.push_widget(scroller)

  def _show_folders(self):
    bundles = big_bundles()
    if not bundles:
      gui_app.push_widget(BigDialog(title="no models available",
                                    description="No big models are listed yet. Connect to the internet and refresh the model list."))
      return
    folders = self._get_grouped_bundles(bundles)
    default_btn = BigButton(default_model_name().lower())
    default_btn.set_click_callback(self._select_default)
    folder_buttons = [default_btn]
    for folder in sorted(folders.keys(), key=lambda f: max((bundle.index for bundle in folders[f]), default=-1), reverse=True):
      btn = BigButton(folder.lower() or "models", f"{len(folders[folder])} models")
      btn.set_click_callback(lambda f=folder: self._select_folder(f))
      folder_buttons.append(btn)
    self._push_selection_view(folder_buttons)

  def _pop_to_main(self):
    gui_app.pop_widgets_to(self)
    self._scroller.scroll_panel.set_offset(0.0)

  def _select_model(self, bundle):
    ui_state.params.put("ModelManager_DownloadRef", bundle.ref)
    self._pop_to_main()

  def _select_default(self):
    ui_state.params.remove(ACTIVE_BUNDLE_KEYS["chestnut"])
    self._pop_to_main()

  def _confirm_clear_cache(self):
    icon = gui_app.texture("icons_mici/settings/network/new/trash.png", 54, 64)
    gui_app.push_widget(BigConfirmationDialog("slide to\nclear cache", icon,
                                              lambda: ui_state.params.put_bool("ModelManager_ClearCache", True), red=True))

  def _refresh_models(self):
    refresh_model_list()
    self._refresh_start = time.monotonic()

  def _select_folder(self, folder_name):
    folders = self._get_grouped_bundles(big_bundles())
    btns = []
    for bundle in sorted(folders.get(folder_name, []), key=lambda b: b.index, reverse=True):
      note = big_model_note(bundle.ref)
      btn = BigButton(bundle.displayName.lower(), value=note.lower() if note else "")
      btn.set_click_callback(lambda b=bundle: self._select_model(b))
      btns.append(btn)
    self._push_selection_view(btns)

  def hide_event(self):
    super().hide_event()
    if self._was_downloading:
      device.set_override_interactive_timeout(None)
      self._was_downloading = False

  def show_event(self):
    super().show_event()
    self.link_toggle._load_value()

  def _update_state(self):
    super()._update_state()

    self.select_model_btn.set_enabled(ui_state.is_offroad())
    self.cancel_download_btn.set_visible(False)
    info = self.current_model_info
    info.current_model_header._shimmer = False
    info.info_header._shimmer = False

    manager = self.model_manager
    self._download_frame += 1
    if self._download_frame % max(1, gui_app.target_fps // 2) == 0:
      self._download_progress = self._download_progress + "." if len(self._download_progress) < 3 else ""
      self.link_toggle._load_value()
      self.link_toggle.set_visible(link_toggle_meaningful())

    selected = manager.selectedBundle if ui_state.sm.alive["modelManagerSP"] else None
    is_downloading = bool(selected and selected.status == DS.downloading)
    if self._was_downloading and not is_downloading:
      device.set_override_interactive_timeout(None)
    self._was_downloading = is_downloading

    # the manager is offroad only, so an onroad clear or refresh would never be serviced
    clearing = ui_state.params.get_bool("ModelManager_ClearCache")
    self.clear_cache_btn.set_enabled(ui_state.is_offroad() and not is_downloading and not clearing)
    if clearing:
      self.clear_cache_btn.set_value("clearing...")
      self._cache_size_time = 0.0
    elif (now := time.monotonic()) - self._cache_size_time > 0.5:
      self._cache_size_time = now
      self.clear_cache_btn.set_value(f"{model_cache_size_mb():.1f} MB")

    refreshing = refresh_in_progress(self._refresh_start)
    self.refresh_btn.set_enabled(ui_state.is_offroad() and not is_downloading and not refreshing)
    self.refresh_btn.set_value("fetching..." if refreshing else "")

    info.current_model_header.set_text("active model")
    active_text, info_header, info_text = _model_info()
    info.current_model_text.set_text(active_text)
    info.info_header.set_text(info_header)
    info.info_text.set_text(info_text)

    if selected and selected.status == DS.failed:
      info.info_header.set_text("error" + self._download_progress)
      info.info_text.set_text("download failed")

    elif is_downloading:
      self.cancel_download_btn.set_visible(ui_state.params.get("ModelManager_DownloadRef") is not None)
      device.set_override_interactive_timeout(5)
      progress, count, verifying, canceling, speed = 0.0, 0, False, False, 0.0
      for model in selected.models:
        count += 1
        p = model.artifact.downloadProgress
        if p.status in (DS.downloading, DS.verifying):
          progress += p.progress
          verifying = verifying or p.status == DS.verifying
          canceling = canceling or p.canceling
          speed = max(speed, p.speed)  # one file downloads at a time, so the non-zero speed is the live one
        elif p.status in (DS.downloaded, DS.cached):
          progress += 100.0

      info.current_model_header.set_text("canceling..." if canceling else "verifying" if verifying else "downloading")
      self.cancel_download_btn.set_text("cancel verification" if verifying else "cancel download")
      info.current_model_header._shimmer = True
      name_text = selected.internalName.lower()
      if queued := queued_name(selected.ref):
        name_text += f"  |  {queued.lower()} queued"
      info.current_model_text.set_text(name_text)
      info.info_header.set_text("progress" + self._download_progress)
      info.info_header._shimmer = True
      progress_text = f"{progress / max(count, 1):.2f}%"
      if not verifying and not canceling:
        progress_text += f"  |  {speed / 1024 ** 2:.1f} MB/s" if speed > 0 else "  |  --.- MB/s"
      info.info_text.set_text(progress_text)

    elif selected and selected.status == DS.downloaded:
      info.info_header.set_text("downloaded")
      info.info_text.set_text("downloaded")
