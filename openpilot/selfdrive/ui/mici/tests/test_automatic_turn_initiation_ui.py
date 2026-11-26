import pytest


def _init_window():
  import raylib_nb as rl
  from openpilot.system.ui.lib.application import gui_app
  if not rl.is_window_ready():
    rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
    rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
    rl.init_window(536, 240, "ati")
    gui_app._load_fonts()


def test_ati_toggle_placement_confirm_and_migration(params_root, monkeypatch):
  try:
    _init_window()
  except Exception as e:
    pytest.skip(str(e))

  from openpilot.common.params import Params
  from openpilot.common.params_compat import get_bool, put_bool
  from openpilot.selfdrive.controls.lib.turn_intent import ATI_PARAM, LEGACY_TURN_PARAMS
  from openpilot.selfdrive.ui.mici.layouts.settings.driving import (
    ATI_CONFIRM_CARDS,
    AutomaticTurnInitiationConfirmPage,
    DrivingLayoutMici,
  )
  from openpilot.selfdrive.ui.mici.widgets.button import GreyBigButton
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationCircleButton, BigConfirmationDialog
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.system.ui.lib.application import MousePos, gui_app

  monkeypatch.setattr(ui_state, "params", Params())

  # Default state is off
  clean_layout = DrivingLayoutMici()
  assert get_bool(ui_state.params, ATI_PARAM, False) is False
  assert clean_layout._ati_btn._checked is False

  # Seed legacy params to exercise migration on layout init
  for k in LEGACY_TURN_PARAMS:
    put_bool(ui_state.params, k, True, block=True)
  layout = DrivingLayoutMici()
  assert get_bool(ui_state.params, ATI_PARAM, False) is True
  assert layout._ati_btn._checked is True

  # Turning off is immediate, no confirmation push
  pushed = []
  monkeypatch.setattr(gui_app, "push_widget", lambda w: pushed.append(w))
  layout._ati_btn._handle_mouse_release(MousePos(0, 0))
  assert pushed == []
  assert get_bool(ui_state.params, ATI_PARAM, True) is False

  # Placement right after auto lane change, no section label
  items = layout._scroller._items
  alc_idx = items.index(layout._alc_btn)
  assert items[alc_idx + 1] is layout._ati_btn
  assert not hasattr(layout, "_turn_desires_header")
  assert not hasattr(layout, "_turn_desires_toggle")
  assert layout._ati_btn._label.text == "automatic turn initiation"

  # Enabling opens confirm page and leaves param off until confirmed
  layout._ati_btn._handle_mouse_release(MousePos(0, 0))
  assert len(pushed) == 1
  confirm_page = pushed[0]
  assert isinstance(confirm_page, AutomaticTurnInitiationConfirmPage)
  assert layout._ati_btn._checked is False
  assert get_bool(ui_state.params, ATI_PARAM, False) is False

  # Verify GreyBigButton texts on the confirm page
  buttons = [w for w in confirm_page._scroller._items if isinstance(w, GreyBigButton)]
  assert [b._label.text for b in buttons] == ["enabling auto\nturn initiation"] + [""] * len(ATI_CONFIRM_CARDS)
  assert [b._sub_label.text for b in buttons] == ["scroll to continue"] + ATI_CONFIRM_CARDS

  # Exercise slide button -> BigConfirmationDialog, then cancel without confirming
  circle = next(w for w in confirm_page._scroller._items if isinstance(w, BigConfirmationCircleButton))
  circle._click_callback()
  assert len(pushed) == 2
  dialog = pushed[1]
  assert isinstance(dialog, BigConfirmationDialog)
  layout._update_toggles()
  assert get_bool(ui_state.params, ATI_PARAM, False) is False
  assert layout._ati_btn._checked is False

  # Confirming via BigConfirmationDialog sets param and updates toggle
  monkeypatch.setattr(confirm_page, "dismiss", lambda cb=None: cb() if cb else None)
  dialog._confirm_callback()
  assert get_bool(ui_state.params, ATI_PARAM, False) is True
  assert layout._ati_btn._checked is True

  # Refresh preserves confirmed state
  layout._update_toggles()
  assert layout._ati_btn._checked is True
