import pytest


def _init_window():
  import raylib_nb as rl
  from openpilot.system.ui.lib.application import gui_app
  if not rl.is_window_ready():
    rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
    rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
    rl.init_window(536, 240, "toggles")
    gui_app._load_fonts()


def test_braking_toggle_hidden_without_long_and_disabled_onroad(params_root):
  try:
    _init_window()
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.selfdrive.ui.mici.layouts.settings.toggles import TogglesLayoutMici
  except Exception as e:
    pytest.skip(str(e))

  ui_state.has_longitudinal_control = False
  ui_state.started = False
  layout = TogglesLayoutMici()
  toggle = layout._braking_toggle
  assert toggle.is_visible is False
  assert toggle.enabled is True

  ui_state.has_longitudinal_control = True
  assert toggle.is_visible is True
  assert toggle.enabled is True

  ui_state.started = True
  assert toggle.is_visible is True
  assert toggle.enabled is False

  ui_state.started = False
  layout._update_toggles()
  assert toggle.is_visible is True
  assert toggle.enabled is True

  ui_state.has_longitudinal_control = False
  layout._update_toggles()
  assert toggle.is_visible is False
  assert toggle.enabled is True
