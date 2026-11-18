import re
from pathlib import Path

from openpilot.selfdrive.ui.mici.layouts.settings import bluetooth as bt

DK = "AA:BB:CC:DD:EE:01"
SETTINGS = Path(bt.__file__).parent


def dev(connected):
  return {"devices": [{"mac": DK, "name": "DashKit", "rssi": -60, "paired": True, "connected": connected, "dashkit": True}]}


def test_status_text():
  assert bt.status_text(False, dev(True), DK, "0.3.2") == "Bluetooth unavailable on this kernel"
  assert bt.status_text(True, {}, "", "") == "DashKit not paired"
  assert bt.status_text(True, dev(False), DK, "0.3.2") == "DashKit paired, waiting for drive"
  assert bt.status_text(True, dev(True), DK, "0.3.2") == "DashKit connected, firmware 0.3.2"
  assert bt.status_text(True, dev(True), DK, "") == "DashKit connected, firmware unknown"


def test_bars():
  assert [bt.bars(r) for r in (None, -95, -85, -75, -65, -40)] == [0, 0, 1, 2, 3, 4]


def test_hidden_without_hci0(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "HCI0", str(tmp_path / "hci0"))
  assert not bt.bt_available()
  (tmp_path / "hci0").mkdir()
  assert bt.bt_available()
  src = (SETTINGS / "settings.py").read_text()
  assert "bluetooth_btn.set_visible(bt_available)" in src and "bluetooth_btn," in src


def test_no_icons_or_warning_colors():
  src = (SETTINGS / "bluetooth.py").read_text()
  assert ".png" not in src and "texture(" not in src
  assert not re.search(r"rl\.Color\(|ORANGE|RED|red=True", src)
  entry = next(line for line in (SETTINGS / "settings.py").read_text().splitlines() if 'SettingsBigButton("bluetooth"' in line)
  assert "texture" not in entry
