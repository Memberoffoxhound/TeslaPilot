#!/usr/bin/env python3
# Renders the dpbridge kernel consent and progress pages and saves PNGs. On a PC it runs its own Xvfb (needs Xvfb, ffmpeg).
# usage: dpbridge_kernel_screenshot.py [out_dir]
import os
import subprocess
import sys
import time
import types


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

  def remove(self, k, *a, **kw):
    self.store.pop(k, None)


sys.modules.setdefault("openpilot.common.params", types.SimpleNamespace(Params=FakeParams))  # no libparams needed

import numpy as np
import pyray as rl
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.screenshot import write_png
from openpilot.system.dpbridge import kernel_page

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dpbridge-kernel-shots"
os.environ.setdefault("SCALE", "1")


SIZE = f"{gui_app._scaled_width}x{gui_app._scaled_height}"
kernel_page.answer = lambda word: None


def save(name):
  path = os.path.join(OUT, f"{name}.png")
  if hasattr(rl, "cpu"):  # comma's software raylib
    write_png(path, np.array(rl.cpu.screen()[..., :4], dtype=np.uint8)[::-1])
    return
  subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-draw_mouse", "0", "-video_size", SIZE, "-i", os.environ["DISPLAY"],
                  "-frames:v", "1", path], check=True)


def frames(n):
  for i, _ in enumerate(gui_app.render()):
    if i == n:
      break


def fresh():
  gui_app._nav_stack.clear()
  page = kernel_page.KernelPage()
  gui_app.push_widget(page)
  return page


def settings_shots():
  # the entry that brings the page back after "not now": stock kernel, declined
  from openpilot.selfdrive.ui.mici.layouts.settings import settings
  from openpilot.selfdrive.ui.ui_state import ui_state
  ui_state.initial_cruise_speed = 0.0  # no params on a PC
  settings.bt_supported = lambda: False
  settings.declined = lambda: True
  gui_app._nav_stack.clear()
  page = settings.SettingsLayout()
  gui_app.push_widget(page)
  frames(30)
  btn = page._bt_setup_btn
  page._scroller.scroll_to((btn.rect.x + btn.rect.width / 2) - (page.rect.x + page.rect.width / 2), smooth=False)
  frames(20)
  save("settings_set_up")
  btn._click_callback()
  frames(40)
  save("settings_set_up_slider")


def main():
  os.makedirs(OUT, exist_ok=True)
  xvfb = None
  if not hasattr(rl, "cpu"):
    os.environ["DISPLAY"] = ":88"
    xvfb = subprocess.Popen(["Xvfb", ":88", "-nocursor", "-screen", "0", f"{SIZE}x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
  try:
    shots()
  finally:
    gui_app.close()
    if xvfb:
      xvfb.terminate()
  print("\n".join(sorted(os.path.join(OUT, f) for f in os.listdir(OUT))))


def shots():
  gui_app.init_window("dpbridge kernel")
  page = fresh()
  page.command("ask")
  frames(30)
  sc = page._consent._scroller
  for k, item in enumerate([w for w in sc.items if w.is_visible]):
    sc.scroll_to((item.rect.x + item.rect.width / 2) - (page.rect.x + page.rect.width / 2), smooth=False)
    frames(15)
    save(f"consent_{k:02d}")
  # the sliders each circle opens
  for name, btn in (("accept_slider", sc.items[-2]), ("decline_slider", sc.items[-1])):
    btn._click_callback()  # pushes its BigConfirmationDialog
    frames(40)
    save(name)
    gui_app.pop_widget()
    frames(40)
  page = fresh()
  page.command("wait 85")
  frames(20)
  save("progress_00_connecting")
  for k, (pct, title) in enumerate(((10, "installing"), (36, "downloading"), (52, "verifying"), (56, "backing up"),
                                    (64, "writing slot b"), (92, "reading back"), (98, "switching slot"), (100, "rebooting")), 1):
    page.command(f"step {pct} {title}")
    frames(5)
    save(f"progress_{k:02d}_{title.replace(' ', '_')}")
  for name, note in (("note_failed", "kernel not\\ninstalled|openpilot is starting"), ("note_no_network", "no network,\\nskipped|tries next boot")):
    page.command(f"note {note}")
    frames(5)
    save(name)
  settings_shots()


if __name__ == "__main__":
  main()
