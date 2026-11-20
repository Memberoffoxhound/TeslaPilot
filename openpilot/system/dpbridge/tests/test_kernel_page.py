# The kernel consent page: its cards from kernel_warning.txt, and the page process under Xvfb when raylib is here.
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from openpilot.system.dpbridge.kernel_warning import WARNING, cards

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG.parents[2]
UI = importlib.util.find_spec("raylib_nb") is not None and shutil.which("Xvfb") is not None


def test_cards_from_the_warning_file():
  c = cards()
  assert Path(WARNING) == ROOT / "tools/dpbridge/kernel_warning.txt"
  assert c[0] == ("custom kernel\nrequired", "for Bluetooth", "warning")
  assert ("caution: a bad\nflash can brick\nthe comma", "", "red") in c
  assert ("", "Recovery may need QDL mode and a full reflash that wipes your data.", "") in c
  assert {i for _, _, i in c} <= {"", "warning", "red", "restore"} and len(c) == 12


def test_copy_rules():
  text = Path(WARNING).read_text()
  assert "\u2014" not in text and "Hotz" not in text


def test_accept_and_red_decline_are_comma_s_confirm_circles():
  src = (PKG / "kernel_page.py").read_text()
  assert 'BigConfirmationCircleButton("install\\nkernel"' in src
  assert 'BigConfirmationCircleButton("not now", gui_app.texture("icons_mici/setup/cancel.png", 64, 64), on_decline, red=True)' in src
  assert "Params(" not in src and "common.params" not in src  # runs before anything is built


@pytest.fixture
def xvfb():
  if not UI:
    pytest.skip("needs raylib_nb and Xvfb")
  p = subprocess.Popen(["Xvfb", ":89", "-nocursor", "-screen", "0", "536x240x24"], stderr=subprocess.DEVNULL)
  time.sleep(1)
  yield dict(os.environ, DISPLAY=":89", SCALE="1", PYTHONPATH=str(ROOT))
  p.terminate()


def test_cards_fit(xvfb):
  code = """
from openpilot.system.ui.lib.application import gui_app
gui_app.init_window("t")
from openpilot.system.dpbridge.kernel_page import ConsentPage
page = ConsentPage(lambda: None, lambda: None)
for c in page._scroller.items[:-2]:
  h = c._label.get_content_height(c._title_width_hint()) if c.text else 0
  h += c._sub_label.get_content_height(c._subtitle_width_hint()) if c.value else 0
  assert h <= c.rect.height - 2 * c.LABEL_VERTICAL_PADDING, (c.text, c.value, h)
print("fit", len(page._scroller.items))
"""
  r = subprocess.run([sys.executable, "-c", code], env=xvfb, capture_output=True, text=True, timeout=60)
  assert r.returncode == 0 and "fit 14" in r.stdout, r.stderr[-2000:]


def test_page_process_takes_commands_and_exits_at_eof(xvfb):
  p = subprocess.Popen([sys.executable, str(PKG / "kernel_page.py")], env=xvfb, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
  for ln in ("ask", "wait 90", "step 64 writing slot b", "note kernel not\\ninstalled|openpilot is starting", "bogus"):
    p.stdin.write(ln + "\n")
    p.stdin.flush()
    time.sleep(0.3)
  assert p.poll() is None
  p.stdin.close()
  p.wait(timeout=20)
  out, err = p.stdout.read(), p.stderr.read()
  assert p.returncode == 0 and out == "", err[-2000:]  # only answers on stdout


def test_answers_have_their_own_fd():
  src = (PKG / "kernel_page.py").read_text()
  assert "os.dup2(2, 1)" in src and "file=ANSWER" in src


def test_accept_and_not_now_answer_once(xvfb):
  code = """
from openpilot.system.ui.lib.application import gui_app
gui_app.init_window("t")
from openpilot.system.dpbridge import kernel_page
said = []
kernel_page.answer = said.append
for word in ("accept", "later"):
  page = kernel_page.KernelPage()
  page.command("ask")
  assert page._view is page._consent
  page._on_accept() if word == "accept" else page._done("later")
  page._on_accept()  # a second slide answers nothing more
  assert said[-1] == word
  assert page._view is (page._progress if word == "accept" else None)
assert said == ["accept", "later"], said
print("ok")
"""
  r = subprocess.run([sys.executable, "-c", code], env=xvfb, capture_output=True, text=True, timeout=60)
  assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-2000:]
