import os
import time
from collections.abc import Callable

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigParamControl, GreyBigButton
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller

# dpbridge Bluetooth page. btagentd does the work; this page sends DpbCmd and shows DpbStatus.
HCI0 = "/sys/class/bluetooth/hci0"
BLUEALSA = "/usr/bin/bluealsa"
PAIR_NOTE = ["On your phone, open DashPilot, go to DashKit settings, and tap Open pairing.",
             "Then tap pair here within 2 minutes.",
             "If DashKit has never been paired, just tap pair."]
SHARE_NOTE = ["DashKit streams to one device at a time.",
              "While the comma is logging, DashPilot on your phone shows no live data.",
              "Turn off log DashKit to give it back."]


def bt_available() -> bool:
  return os.path.exists(HCI0)


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


class ChoicePage(NavScroller):
  # grey note lines, then one button per choice; a choice closes the page first
  def __init__(self, notes: list[str], choices: list[tuple[str, Callable[[], None]]]):
    super().__init__()
    widgets = [GreyBigButton("", n) for n in notes]
    for label, fn in choices:
      btn = BigButton(label)
      btn.set_click_callback(lambda fn=fn: self.dismiss(fn))
      widgets.append(btn)
    self._scroller.add_widgets(widgets)


class BluetoothLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._status: dict = {}
    self._addr = ""
    self._available = False
    self._passkey_shown = ""
    self._dynamic: dict[str, BigButton] = {}
    self._last_read = 0.0
    self._last_ping = 0.0

    self._status_btn = GreyBigButton("", "")
    self._log_toggle = BigParamControl("log DashKit", "DashKitBridge")
    self._find_btn = BigButton("find DashKit")
    self._find_btn.set_click_callback(lambda: self._send("scan"))
    self._forget_btn = BigButton("forget DashKit")
    self._forget_btn.set_click_callback(self._confirm_forget)
    self._share_notes = [GreyBigButton("", n) for n in SHARE_NOTE]
    self._discover_btn = BigButton("make discoverable", "for phones, 2 min")
    self._discover_btn.set_click_callback(lambda: self._send("discoverable"))

    for w in (self._log_toggle, self._forget_btn, *self._share_notes):
      w.set_visible(lambda: bool(self._addr))
    self._find_btn.set_visible(lambda: self._available and not self._addr)
    self._discover_btn.set_visible(lambda: os.path.exists(BLUEALSA))
    self._scroller.add_widgets([self._status_btn, self._log_toggle, self._find_btn, self._forget_btn, *self._share_notes,
                                self._discover_btn])

  def _send(self, cmd: str):
    self._params.put("DpbCmd", cmd)

  def _read(self) -> tuple[bool, dict, str, str]:
    return bt_available(), self._params.get("DpbStatus") or {}, self._params.get("DashKitAddr") or "", \
      self._params.get("DashKitVersion") or ""

  def _confirm_forget(self):
    gui_app.push_widget(ChoicePage(["The comma forgets DashKit. DashKit keeps its own list of up to 8 bonds."],
                                   [("forget DashKit", lambda: self._send(f"forget:{self._addr}"))]))

  def _device_button(self, d: dict) -> BigButton:
    mac = d["mac"]
    if d["dashkit"]:
      btn = BigButton("pair DashKit", f"signal {bars(d['rssi'])}/4")
      btn.set_click_callback(lambda: gui_app.push_widget(ChoicePage(PAIR_NOTE, [("pair", lambda: self._send(f"pair:{mac}"))])))
    else:
      btn = BigButton(f"forget {d['name'] or mac}", "phone, paired")
      btn.set_click_callback(lambda: gui_app.push_widget(ChoicePage([f"Forget {d['name'] or mac}?"],
                                                                     [("forget", lambda: self._send(f"forget:{mac}"))])))
    return btn

  def _update_state(self):
    super()._update_state()
    if time.monotonic() - self._last_read < 0.5:
      return
    self._last_read = time.monotonic()
    # keeps btagentd publishing DpbStatus while this page is on screen
    if self._last_read - self._last_ping > 5 and not self._params.get("DpbCmd"):
      self._send("status")
      self._last_ping = self._last_read
    self._available, self._status, self._addr, version = self._read()
    st = self._status
    text = st.get("error") or status_text(self._available, st, self._addr, version)
    if st.get("scanning"):
      text = "looking for DashKit..."
    if text != self._status_btn.value:
      self._status_btn.set_value(text)

    # unpaired DashKits from the last scan, and phones we are bonded with
    want = {d["mac"]: d for d in st.get("devices", [])
            if (d["dashkit"] and not d["paired"] and not self._addr) or (d["paired"] and not d["dashkit"])}
    if want.keys() != self._dynamic.keys():
      for mac in self._dynamic.keys() - want.keys():
        self._scroller.items.remove(self._dynamic.pop(mac))
      for mac in want.keys() - self._dynamic.keys():
        self._dynamic[mac] = self._device_button(want[mac])
        self._scroller.add_widget(self._dynamic[mac])

    passkey = st.get("passkey", "")
    if passkey and passkey != self._passkey_shown:
      code = f"{passkey[:3]} {passkey[3:]}"
      gui_app.push_widget(ChoicePage([f"Does your phone show {code}?"],
                                     [("pair", lambda: self._send("confirm:1")), ("cancel", lambda: self._send("confirm:0"))]))
    self._passkey_shown = passkey
