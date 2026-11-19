import os
import time
from collections.abc import Callable

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import ForgetButton, LoadingAnimation
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigParamControl, GreyBigButton, LABEL_COLOR
from openpilot.system.dpbridge.radio_status import read as read_bt_radio
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import NavScroller

import raylib_nb as rl

# dpbridge Bluetooth: the toggle lives on the main Settings list. This page is the
# devices card, styled like the Wi-Fi search list. UI only writes DpbCmd.
HCI0 = "/sys/class/bluetooth/hci0"
WCN = "/sys/module/hci_uart/parameters/wcn3990"
SHARE_NOTE = ["DashKit streams to one device at a time.",
              "While the comma is logging, DashPilot on your phone shows no live data.",
              "Turn off log DashKit to give it back."]


def bt_supported() -> bool:
  return os.path.exists(WCN)


def bt_available() -> bool:
  return os.path.exists(HCI0)


def _send(params: Params, cmd: str):
  params.put("DpbCmd", cmd)


class DeviceScanningButton(BigButton):
  def __init__(self):
    super().__init__("", "searching for devices")
    self.set_enabled(False)
    self._loading_animation = LoadingAnimation()

  def _draw_content(self, btn_y: float):
    super()._draw_content(btn_y)
    anim = self._loading_animation
    x = self._rect.x + self._rect.width - anim.rect.width - 40
    y = btn_y + self._rect.height - anim.rect.height - 30
    anim.set_position(x, y)
    anim.render()


class DeviceButton(BigButton):
  LABEL_PADDING = 98
  LABEL_WIDTH = 402 - 98 - 28
  SUB_LABEL_WIDTH = 402 - BigButton.LABEL_HORIZONTAL_PADDING * 2

  def __init__(self, device: dict, on_forget: Callable[[str], None]):
    super().__init__(device.get("name") or device.get("mac") or "", scroll=True)
    self._device = device
    self._on_forget = on_forget
    self._forgetting = False
    self._busy = ""  # pairing... / connecting...
    self._bt_icon = gui_app.texture("icons_mici/bluetooth.png", 32, 48)
    self._forget_btn = ForgetButton(self._forget)
    self._check_txt = gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 32, 32)

  def update_device(self, device: dict):
    self._device = device
    name = device.get("name") or device.get("mac") or ""
    if name != self.text:
      self.set_text(name)

  def set_busy(self, text: str):
    self._busy = text

  def on_forgotten(self):
    self._forgetting = False

  @property
  def mac(self) -> str:
    return self._device.get("mac") or ""

  @property
  def forgetting(self) -> bool:
    return self._forgetting

  def _forget(self):
    if self._forgetting:
      return
    self._forgetting = True
    self._on_forget(self.mac)

  def _show_forget_btn(self) -> bool:
    if self._forgetting:
      return False
    return bool(self._device.get("paired") or self._device.get("connected") or self._busy)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if self._show_forget_btn() and rl.check_collision_point_rec(rl.Vector2(mouse_pos.x, mouse_pos.y), self._forget_btn.rect):
      return
    super()._handle_mouse_release(mouse_pos)

  def _get_label_font_size(self):
    return 48

  def _update_state(self):
    super()._update_state()
    connected = bool(self._device.get("connected"))
    paired = bool(self._device.get("paired"))
    if self._forgetting:
      self.set_enabled(False)
      self.set_value("forgetting...")
      self._sub_label.set_color(rl.Color(255, 255, 255, int(255 * 0.585)))
      self._sub_label.set_font_weight(FontWeight.ROMAN)
    elif self._busy:
      self.set_enabled(False)
      self.set_value(self._busy)
      self._sub_label.set_color(rl.Color(255, 255, 255, int(255 * 0.585)))
      self._sub_label.set_font_weight(FontWeight.ROMAN)
    elif connected:
      self.set_enabled(True)
      self.set_value("connected")
      self._sub_label.set_color(rl.Color(255, 255, 255, int(255 * 0.585)))
      self._sub_label.set_font_weight(FontWeight.ROMAN)
    elif paired:
      self.set_enabled(True)
      self.set_value("paired")
      self._sub_label.set_color(rl.Color(255, 255, 255, int(255 * 0.9)))
      self._sub_label.set_font_weight(FontWeight.SEMI_BOLD)
    else:
      self.set_enabled(True)
      self.set_value("pair")
      self._sub_label.set_color(rl.Color(255, 255, 255, int(255 * 0.9)))
      self._sub_label.set_font_weight(FontWeight.SEMI_BOLD)

  def _draw_content(self, btn_y: float):
    self._label.set_color(LABEL_COLOR)
    label_rect = rl.Rectangle(self._rect.x + self.LABEL_PADDING, btn_y + self.LABEL_VERTICAL_PADDING,
                              self.LABEL_WIDTH, self._rect.height - self.LABEL_VERTICAL_PADDING * 2)
    self._label.render(label_rect)

    if self.value:
      sub_label_x = self._rect.x + self.LABEL_HORIZONTAL_PADDING
      label_y = btn_y + self._rect.height - self.LABEL_VERTICAL_PADDING
      sub_label_w = self.SUB_LABEL_WIDTH - (self._forget_btn.rect.width if self._show_forget_btn() else 0)
      sub_label_height = self._sub_label.get_content_height(sub_label_w)

      if self._device.get("connected") and not self._forgetting:
        check_y = int(label_y - sub_label_height + (sub_label_height - self._check_txt.height) / 2)
        rl.draw_texture_ex(self._check_txt, rl.Vector2(sub_label_x, check_y), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * 0.9 * 0.65)))
        sub_label_x += self._check_txt.width + 14

      sub_label_rect = rl.Rectangle(sub_label_x, label_y - sub_label_height, sub_label_w, sub_label_height)
      self._sub_label.render(sub_label_rect)

    rl.draw_texture_ex(self._bt_icon, rl.Vector2(self._rect.x + 30, btn_y + 30), 0.0, 1.0, rl.Color(255, 255, 255, int(255 * 0.9)))

    if self._show_forget_btn():
      self._forget_btn.render(rl.Rectangle(
        self._rect.x + self._rect.width - self._forget_btn.rect.width,
        btn_y + self._rect.height - self._forget_btn.rect.height,
        self._forget_btn.rect.width,
        self._forget_btn.rect.height,
      ))

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(lambda: touch_callback() and not self._forget_btn.is_pressed)
    self._forget_btn.set_touch_valid_callback(touch_callback)


class ChoicePage(NavScroller):
  def __init__(self, notes: list[str], choices: list[tuple[str, Callable[[], None]]]):
    super().__init__()
    widgets = [GreyBigButton("", n) for n in notes]
    for label, fn in choices:
      btn = BigButton(label)
      btn.set_click_callback(lambda fn=fn: self.dismiss(fn))
      widgets.append(btn)
    self._scroller.add_widgets(widgets)


class BluetoothUIMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._status: dict = {}
    self._addr = ""
    self._last_read = 0.0
    self._last_ping = 0.0
    self._passkey_shown = ""
    self._busy: dict[str, str] = {}
    self._scanning_btn = DeviceScanningButton()
    self._log_toggle = BigParamControl("log DashKit", "DashKitBridge")
    self._share_notes = [GreyBigButton("", n) for n in SHARE_NOTE]
    self._log_toggle.set_visible(lambda: bool(self._addr))
    for n in self._share_notes:
      n.set_visible(lambda: bool(self._addr))
    self._scroller.add_widgets([self._scanning_btn])

  def show_event(self):
    super().show_event()
    _send(self._params, "scan")  # btagentd starts discovery and discoverable while the page is open

  def _forget(self, mac: str):
    _send(self._params, f"forget:{mac}")

  def _tap(self, mac: str):
    btn = next((b for b in self._scroller.items if isinstance(b, DeviceButton) and b.mac == mac), None)
    if btn is None:
      return
    d = btn._device
    if d.get("connected"):
      btn.set_busy("disconnecting...")
      self._busy[mac] = "disconnecting..."
      _send(self._params, f"disconnect:{mac}")
    elif d.get("paired"):
      btn.set_busy("connecting...")
      self._busy[mac] = "connecting..."
      _send(self._params, f"connect:{mac}")
    else:
      btn.set_busy("pairing...")
      self._busy[mac] = "pairing..."
      _send(self._params, f"pair:{mac}")

  def _devices(self) -> list[dict]:
    return list(self._status.get("devices") or [])

  def _update_buttons(self):
    want = {d["mac"]: d for d in self._devices() if d.get("mac")}
    existing = {btn.mac: btn for btn in self._scroller.items if isinstance(btn, DeviceButton)}
    for mac, d in want.items():
      if mac in existing:
        existing[mac].update_device(d)
        if mac in self._busy:
          if (self._busy[mac] == "pairing..." and d.get("paired")) or \
             (self._busy[mac] == "connecting..." and d.get("connected")) or \
             (self._busy[mac] == "disconnecting..." and not d.get("connected")):
            existing[mac].set_busy("")
            self._busy.pop(mac, None)
          else:
            existing[mac].set_busy(self._busy[mac])
      else:
        btn = DeviceButton(d, self._forget)
        btn.set_click_callback(lambda mac=mac: self._tap(mac))
        self._scroller.add_widget(btn)
    for mac in list(existing):
      if mac not in want and not existing[mac].forgetting:
        self._scroller.items.remove(existing[mac])
        self._busy.pop(mac, None)

    # connected first, then paired, then the rest, scanning last, dashkit notes after that
    btns = [b for b in self._scroller.items if isinstance(b, DeviceButton)]
    def key(b: DeviceButton):
      d = b._device
      return (0 if d.get("connected") else 1 if d.get("paired") else 2, (d.get("name") or d.get("mac") or "").lower())
    ordered = sorted(btns, key=key)
    rest = [w for w in self._scroller.items if not isinstance(w, DeviceButton)]
    items = list(ordered)
    if self._scanning_btn in rest:
      items.append(self._scanning_btn)
    for w in (self._log_toggle, *self._share_notes):
      if w not in self._scroller.items:
        self._scroller.add_widget(w)
      items.append(w)
    self._scroller.items[:] = items

  def _update_state(self):
    super()._update_state()
    if time.monotonic() - self._last_read < 0.5:
      return
    self._last_read = time.monotonic()
    if self._last_read - self._last_ping > 5 and not self._params.get("DpbCmd"):
      _send(self._params, "status")
      self._last_ping = self._last_read
    self._status = self._params.get("DpbStatus") or {}
    self._addr = self._params.get("DashKitAddr") or ""
    if self._status.get("error") and not self._passkey_shown:
      pass
    self._update_buttons()

    passkey = self._status.get("passkey", "")
    if passkey and passkey != self._passkey_shown:
      code = f"{passkey[:3]} {passkey[3:]}"
      gui_app.push_widget(ChoicePage([f"Does your phone show {code}?"],
                                     [("pair", lambda: _send(self._params, "confirm:1")),
                                      ("cancel", lambda: _send(self._params, "confirm:0"))]))
    self._passkey_shown = passkey


# kept for tests of the old status lines used by DashKit logging
def status_text(available: bool, status: dict, addr: str, version: str) -> str:
  if not available:
    return "Bluetooth unavailable on this kernel"
  if not addr:
    return "DashKit not paired"
  if any(d["mac"] == addr and d["connected"] for d in status.get("devices", [])):
    return f"DashKit connected, firmware {version or 'unknown'}"
  return "DashKit paired, waiting for drive"


def bars(rssi: int | None) -> int:
  return 0 if rssi is None else sum(rssi > t for t in (-90, -80, -70, -60))


BluetoothLayoutMici = BluetoothUIMici
