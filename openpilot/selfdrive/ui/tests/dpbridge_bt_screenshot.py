#!/usr/bin/env python3
# Renders the dpbridge Bluetooth page in a few states and saves PNGs. On a PC it runs its own Xvfb (needs Xvfb, ffmpeg).
# usage: dpbridge_bt_screenshot.py [out_dir]
import os
import subprocess
import sys
import time
import types

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dpbridge-shots"
DK = "AA:BB:CC:DD:EE:01"
PHONE = "AA:BB:CC:DD:EE:02"


class FakeParams:
  store: dict = {}

  def __init__(self, *a, **kw):
    pass

  def get(self, k, *a, **kw):
    return self.store.get(k)

  def get_bool(self, k, *a, **kw):
    return bool(self.store.get(k))

  def put(self, k, v, *a, **kw):
    self.store[k] = v

  put_bool = put


os.environ.setdefault("SCALE", "1")
sys.modules["openpilot.common.params"] = types.SimpleNamespace(Params=FakeParams)  # no libparams needed

import numpy as np
import pyray as rl
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.screenshot import write_png
from openpilot.selfdrive.ui.mici.layouts.settings import bluetooth

STATES = {
  "not_paired_found": ({}, {"scanning": False, "devices": [
    {"mac": DK, "name": "DashKit", "rssi": -64, "paired": False, "connected": False, "dashkit": True}]}),
  "connected": ({"DashKitAddr": DK, "DashKitVersion": "0.3.2", "DashKitBridge": True}, {"devices": [
    {"mac": DK, "name": "DashKit", "rssi": -60, "paired": True, "connected": True, "dashkit": True},
    {"mac": PHONE, "name": "iPhone", "rssi": None, "paired": True, "connected": False, "dashkit": False}]}),
  "phone_code": ({}, {"passkey": "482913", "devices": []}),
  "no_kernel": ({}, {}),
  "pair_dialog": ({}, {}),
}


def save(path):
  if hasattr(rl, "cpu"):  # comma's software raylib
    write_png(path, np.array(rl.cpu.screen()[..., :4], dtype=np.uint8)[::-1])  # rows are bottom up
    return
  # desktop raylib: the window fills our Xvfb screen, grab the last presented frame
  subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", SIZE, "-i", os.environ["DISPLAY"],
                  "-frames:v", "1", path], check=True)


def frames(n):
  for i, _ in enumerate(gui_app.render()):
    if i == n:
      break


def shoot(name, params, status, available=True):
  # one frame per visible row, stitched left to right into bt_<name>.png
  FakeParams.store = dict(params, DpbStatus=status)
  bluetooth.bt_available = lambda: available
  gui_app._nav_stack.clear()
  page = bluetooth.BluetoothLayoutMici()
  gui_app.push_widget(page)
  if name == "pair_dialog":
    gui_app.push_widget(bluetooth.ChoicePage(bluetooth.PAIR_NOTE, [("pair", lambda: None)]))
  frames(60)
  top = gui_app._nav_stack[-1]  # the phone code page pushes itself on top
  scroller = top._scroller
  parts = []
  for k, item in enumerate([w for w in scroller.items if w.is_visible]):
    scroller.scroll_to((item.rect.x + item.rect.width / 2) - (top.rect.x + top.rect.width / 2), smooth=False)
    frames(10)
    parts.append(os.path.join(OUT, f".{name}_{k}.png"))
    save(parts[-1])
  out = os.path.join(OUT, f"bt_{name}.png")
  subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *sum((["-i", p] for p in parts), []),
                  "-filter_complex", f"hstack=inputs={len(parts)}" if len(parts) > 1 else "null", out], check=True)
  for p in parts:
    os.remove(p)


SIZE = f"{gui_app._scaled_width}x{gui_app._scaled_height}"


def main():
  os.makedirs(OUT, exist_ok=True)
  xvfb = None
  if not hasattr(rl, "cpu"):
    os.environ["DISPLAY"] = ":87"
    xvfb = subprocess.Popen(["Xvfb", ":87", "-nocursor", "-screen", "0", f"{SIZE}x24"], stderr=subprocess.DEVNULL)
    time.sleep(1)
  gui_app.init_window("dpbridge bluetooth")
  for name, (params, status) in STATES.items():
    shoot(name, params, status, available=name != "no_kernel")
  gui_app.close()
  if xvfb:
    xvfb.terminate()
  print("\n".join(sorted(os.path.join(OUT, f) for f in os.listdir(OUT))))


if __name__ == "__main__":
  main()
