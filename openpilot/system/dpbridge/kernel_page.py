#!/usr/bin/env python3
# dpbridge kernel consent and install progress, run by tools/dpbridge/boot.py before manager (no Params, nothing built).
# stdin: "ask", "wait <s>", "step <pct> <title>", "note <title>|<text>". stdout: "accept" or "later".
import os
import select
import sys
import time

import raylib_nb as rl

from openpilot.system.dpbridge.kernel_warning import cards
from openpilot.system.ui.lib.application import gui_app, FontWeight, TextAlignmentVertical
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import Scroller
from openpilot.selfdrive.ui.mici.widgets.button import GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationCircleButton

ICONS = {"warning": ("icons_mici/setup/warning.png", 64, 58), "red": ("icons_mici/setup/red_warning.png", 64, 58),
         "restore": ("icons_mici/setup/restore.png", 64, 64)}


ANSWER = sys.stdout  # main() moves it off fd 1, so library logs can't fill boot.py's pipe


def answer(word: str):
  print(word, file=ANSWER, flush=True)


class ConsentPage(Scroller):
  # comma's terms page layout: warning cards, then the accept circle and the red decline circle, each with its slider
  def __init__(self, on_accept, on_decline):
    super().__init__()
    items = [GreyBigButton(t, x, gui_app.texture(*ICONS[i]) if i in ICONS else None) for t, x, i in cards()]
    accept = BigConfirmationCircleButton("install\nkernel", gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64),
                                         on_accept)
    decline = BigConfirmationCircleButton("not now", gui_app.texture("icons_mici/setup/cancel.png", 64, 64), on_decline, red=True)
    # boot.py powers off after DPB_ASK_S (600 s) without an answer
    off = GreyBigButton("no answer in\n10 min", "the comma shuts down", gui_app.texture(*ICONS["warning"]))
    self._scroller.add_widgets([*items, off, accept, decline])

  def _render(self, rect):
    rl.draw_rectangle_rec(self._rect, rl.BLACK)
    super()._render(rect)


class ProgressView(Widget):
  # the mici updater's progress page: step title on top, big percent below
  def __init__(self):
    super().__init__()
    self._title = UnifiedLabel("", 64, text_color=rl.Color(255, 255, 255, int(255 * 0.9)), font_weight=FontWeight.DISPLAY, line_height=0.8)
    self._value = UnifiedLabel("", 132, text_color=rl.Color(255, 255, 255, int(255 * 0.9 * 0.65)), font_weight=FontWeight.ROMAN,
                               alignment_vertical=TextAlignmentVertical.BOTTOM)
    self._until = 0.0

  def set(self, title: str, value: str):
    self._title.set_text(title + "...")
    self._value.set_text(value)
    self._until = 0.0

  def countdown(self, secs: float):
    self.set("connecting", f"{int(secs)} s")
    self._until = time.monotonic() + secs

  def _update_state(self):
    if self._until:
      self._value.set_text(f"{max(0, int(self._until - time.monotonic() + 0.99))} s")

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    self._title.render(rl.Rectangle(rect.x + 12, rect.y + 2, rect.width, self._title.get_content_height(int(rect.width - 20))))
    self._value.render(rl.Rectangle(rect.x + 12, rect.y + 18, rect.width, rect.height))


class KernelPage(Widget):
  def __init__(self):
    super().__init__()
    self._consent = ConsentPage(self._on_accept, lambda: self._done("later"))
    self._progress = ProgressView()
    self._note = GreyBigButton("", "")
    self._view: Widget | None = None

  def _on_accept(self):
    if self._done("accept"):
      self._progress.set("starting", "0%")
      self._view = self._progress

  def _done(self, word: str) -> bool:
    # one answer per question
    if self._view is not self._consent:
      return False
    self._view = None
    answer(word)
    return True

  def command(self, line: str):
    cmd, _, arg = line.partition(" ")
    if cmd == "ask":
      self._view = self._consent
    elif cmd == "wait":
      self._progress.countdown(float(arg))
      self._view = self._progress
    elif cmd == "step":
      pct, _, title = arg.partition(" ")
      self._progress.set(title, f"{pct}%")
      self._view = self._progress
    elif cmd == "note":
      title, _, text = arg.partition("|")
      self._note.set_text(title.replace("\\n", "\n"))
      self._note.set_value(text)
      self._view = self._note

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    v = self._view
    if v is self._note:
      w, h = v.rect.width, v.rect.height
      v.render(rl.Rectangle(rect.x + (rect.width - w) / 2, rect.y + (rect.height - h) / 2, w, h))
    elif v is not None:
      v.render(rect)


def read_lines() -> list[str] | None:
  # None at EOF: boot.py is gone
  lines = []
  while select.select([sys.stdin], [], [], 0.0)[0]:
    ln = sys.stdin.readline()
    if not ln:
      return None
    lines.append(ln.strip())
  return lines


def main():
  global ANSWER
  ANSWER = os.fdopen(os.dup(1), "w")
  os.dup2(2, 1)
  sys.stdout = sys.stderr
  gui_app.init_window("dpbridge kernel")
  page = KernelPage()
  gui_app.push_widget(page)
  for _ in gui_app.render():
    lines = read_lines()
    if lines is None:
      gui_app.request_close()
      continue
    for ln in lines:
      page.command(ln)
  gui_app.close()


if __name__ == "__main__":
  main()
