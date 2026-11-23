# zoompilot's Jetlink setting: Off/USB/iOS as stored, offered beside no chestnut
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui import accelerator_link as al


class _Params(dict):
  def get(self, key, return_default=False):
    return super().get(key, 0 if return_default else None)


@pytest.fixture
def ui(monkeypatch):
  ui = SimpleNamespace(params=_Params(), chestnut_present=False, jetlink=SimpleNamespace(port_state=None))
  monkeypatch.setattr(al, 'ui_state', ui)
  return ui


@pytest.mark.parametrize('stored,mode', [(0, 'off'), (1, 'usb'), (2, 'ios'), (7, 'off'), (None, 'off')])
def test_link_mode(ui, stored, mode):
  ui.params['JetlinkLink'] = stored
  assert al.link_mode() == mode


def test_toggle_hidden_beside_a_chestnut(ui):
  assert al.link_toggle_meaningful()
  ui.chestnut_present = True
  assert not al.link_toggle_meaningful()
  ui.params['JetlinkLink'] = 2
  assert al.link_toggle_meaningful(), "a link left on can always be turned off"


def test_toggle_needs_jetlink(ui):
  ui.jetlink = None
  assert not al.link_toggle_meaningful()


def test_link_status(ui):
  assert al.link_status() == ""
  ui.jetlink = SimpleNamespace(port_state="connected", transport="iOS over USB")
  assert al.link_status() == "Jetlink connected: iOS over USB."
  ui.jetlink = SimpleNamespace(port_state="empty")
  assert al.link_status() == "Nothing on the USB port."


def test_big_model_note(ui, monkeypatch):
  monkeypatch.setattr(al.jetlink_adapter, 'model_state', lambda ref: 'ready')
  assert al.big_model_note('r') == "ready on Jetson"
  ui.chestnut_present = True
  assert al.big_model_note('r') is None
