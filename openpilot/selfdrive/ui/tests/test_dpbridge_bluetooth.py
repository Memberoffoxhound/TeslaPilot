import ast
import os
import types
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / "mici/layouts/settings"
DK = "AA:BB:CC:DD:EE:01"


def _load():
  tree = ast.parse((SETTINGS / "bluetooth.py").read_text())
  keep = []
  for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in ("HCI0", "WCN") for t in node.targets):
      keep.append(node)
    if isinstance(node, ast.FunctionDef) and node.name in ("bt_supported", "bt_available", "status_text", "bars"):
      keep.append(node)
  mod = ast.Module(body=keep, type_ignores=[])
  ast.fix_missing_locations(mod)
  ns = {"os": os}
  exec(compile(mod, "bluetooth.py", "exec"), ns)
  return types.SimpleNamespace(**ns)


bt = _load()


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


def test_available_is_hci0(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "HCI0", str(tmp_path / "hci0"))
  # the loaded functions close over module globals; patch the exec namespace via the function globals
  bt.bt_available.__globals__["HCI0"] = str(tmp_path / "hci0")
  assert not bt.bt_available()
  (tmp_path / "hci0").mkdir()
  assert bt.bt_available()


def test_supported_is_the_wcn_sysfs(monkeypatch, tmp_path):
  bt.bt_supported.__globals__["WCN"] = str(tmp_path / "wcn")
  assert not bt.bt_supported()
  (tmp_path / "wcn").write_text("")
  assert bt.bt_supported()


def test_toggle_and_devices_on_main_settings():
  src = (SETTINGS / "settings.py").read_text()
  assert '"bluetooth", "DpbBluetooth"' in src
  assert 'SettingsBigButton("devices"' in src
  assert "set_visible(bt_supported)" in src
  assert 'bt_supported() and self._params.get_bool("DpbBluetooth")' in src
  assert src.find('SettingsBigButton("network"') < src.find("self._bt_toggle")
  assert src.find("self._bt_toggle") < src.find("self._devices_btn")
  assert src.find("self._bt_toggle") < src.find("self._device_button")
  assert "class SettingsBigParamControl" in src


def test_home_icon_next_to_wifi():
  home = Path(__file__).resolve().parents[1] / "mici/layouts/home.py"
  src = home.read_text()
  assert "icons_mici/settings/network/bluetooth.png" in src
  assert "BT_ICON_SIZE = (32, 48)" in src
  wifi = src.find("NetworkIcon()")
  icon = src.find("self._bt_icon,")
  long = src.find("self._long_badge,")
  assert 0 <= wifi < icon < long
  assert "set_visible(self._bt_on)" in src
  assert "set_opacity(0.9 if self._bt_connected else 0.5)" in src
