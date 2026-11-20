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


def test_supported_is_the_kernel_check():
  # every Bluetooth entry point goes through bt_kernel (openpilot/system/dpbridge/tests/test_kernel_ok.py)
  src = (SETTINGS / "bluetooth.py").read_text()
  assert "def bt_supported() -> bool:\n  return bt_kernel()\n" in src
  assert "from openpilot.system.dpbridge.kernel_ok import bt_kernel" in src


def test_home_and_nowplaying_gated_on_the_kernel():
  ui = Path(__file__).resolve().parents[1] / "mici"
  home = (ui / "layouts/home.py").read_text()
  assert "self._bt_icon.set_visible(self._bt_on and bt_kernel())" in home
  card = (ui / "widgets/nowplaying.py").read_text()
  assert "self._state = read_state() if bt_kernel() else {}" in card
  # the card is the only now-playing UI, on home and onroad
  road = (ui / "onroad/augmented_road_view.py").read_text()
  assert "NowPlayingCard()" in road and "read_state" not in road


def test_pairing_panel_only_behind_the_gated_button():
  for f in (Path(__file__).resolve().parents[1] / "mici").rglob("*.py"):
    if f.name != "bluetooth.py" and "BluetoothUIMici()" in f.read_text():
      assert f.name == "settings.py", f


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


def test_settings_shows_why_bluetooth_went_off():
  src = (SETTINGS / "settings.py").read_text()
  assert 'reason = off_reason() if bt_supported() else ""' in src


def test_toggle_sub_label_set_only_on_change():
  # run the two lines against a fake toggle: set_value (a re-layout) only when the text changes
  src = (SETTINGS / "settings.py").read_text()
  start = src.index('    reason = off_reason()')
  lines = src[start:].splitlines()[:3]
  code = "\n".join(ln[4:] for ln in lines)

  class Toggle:
    def __init__(self):
      self.value, self.sets = "", 0

    def get_value(self):
      return self.value

    def set_value(self, v):
      self.value, self.sets = v, self.sets + 1

  t = Toggle()
  me = types.SimpleNamespace(_bt_toggle=t)
  texts = iter(["", "", "off: did not start twice", "off: did not start twice", "off: did not start twice", ""])
  for _ in range(6):
    reason_now = next(texts)
    exec(code, {"off_reason": lambda r=reason_now: r, "bt_supported": lambda: True, "self": me})
  assert t.sets == 2 and t.value == ""


def test_home_icon_next_to_wifi():
  home = Path(__file__).resolve().parents[1] / "mici/layouts/home.py"
  src = home.read_text()
  assert "icons_mici/settings/network/bluetooth.png" in src
  assert "BT_ICON_SIZE = (32, 48)" in src
  wifi = src.find("NetworkIcon()")
  icon = src.find("self._bt_icon,")
  long = src.find("self._long_badge,")
  assert 0 <= wifi < icon < long
  assert "set_visible(self._bt_on and bt_kernel())" in src
  assert "set_opacity(0.9 if self._bt_connected else 0.5)" in src


def test_set_up_entry_only_after_not_now_on_stock():
  src = (SETTINGS / "settings.py").read_text()
  assert 'set_visible(lambda: not bt_supported() and declined())' in src
  i = src.index("def set_up_bt():")
  body = src[i:src.index("\n\n", i)]
  assert "clear_declined()" in body and '"DoReboot", True' in body
  assert 'EngagedConfirmationButton("bluetooth", "reboot"' in src  # slide to reboot, not while engaged
