#!/usr/bin/env python3
# First boot after a dpbridge install (or a change to its pins): run install_userspace.sh once, before manager,
# with comma's spinner on screen. Never blocks openpilot: any failure or the timeout is logged and boot goes on;
# it tries again next boot. Reboots only when the installer flashed the kernel (state=pending).
import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.environ.get("DPB_DIR", "/data/dpbridge")
# own dir: $DIR is root's, this runs as the comma user
STATE = os.environ.get("DPB_BOOT_DIR", "/data/dpbridge_boot")
STAMP = os.path.join(STATE, "stamp")
LOG = os.path.join(STATE, "log")
OUT = os.path.join(STATE, "install.out")  # this run's installer output
FAILS = os.path.join(STATE, "fails")  # "<key> <count>": gives up after MAX_FAILS runs of the same setup
MAX_FAILS = 3
TIMEOUT_S = float(os.environ.get("DPB_BOOT_TIMEOUT_S", "1200"))
KERNEL_WAIT_S = float(os.environ.get("DPB_KERNEL_WAIT_S", "3600"))
STILL = -1  # install() result: the kernel step outlived KERNEL_WAIT_S
MODEL = os.environ.get("DPB_MODEL", "/sys/firmware/devicetree/base/model")
VERSION = os.environ.get("DPB_VERSION", "/VERSION")
SUDO = ["sudo"]
INSTALL = os.path.join(HERE, "install_userspace.sh")
KERNEL = os.path.join(HERE, "kernel.sh")
REBOOT = ["sudo", "reboot"]
# what the install depends on; a change here (code or a pinned sha) runs it again
KEY_FILES = ("install_userspace.sh", "kernel.sh", "lib.sh", "flash_boot.sh", "radio.sh", "attach.sh", "asound.conf",
             "firmware/kernel.env", "firmware/btfw.env", "firmware/firmware.sha256", "firmware/qca.sha256", "bluez/bluez.env")
STEP = re.compile(r"^\[(\d)/(\d)\] ")
KPCT = re.compile(r"^  kernel: .* (\d+)%$")


def read(path: str) -> str:
  try:
    with open(path, "rb") as f:
      return f.read().replace(b"\0", b"").decode(errors="replace").strip()
  except OSError:
    return ""


def slot() -> str:
  try:
    return subprocess.run(["abctl", "--boot_slot"], capture_output=True, text=True, timeout=10).stdout.strip()
  except (OSError, subprocess.SubprocessError):
    return ""


def setup_key() -> str:
  # AGNOS version and slot too: an AGNOS update undoes the rootfs part, the flash reboot moves the slot
  h = hashlib.sha256()
  for f in KEY_FILES:
    h.update(f.encode() + b"\0" + open(os.path.join(HERE, f), "rb").read() + b"\0")
  h.update(f"agnos={read(VERSION)} slot={slot()}".encode())
  return h.hexdigest()


def skip_reason(key: str) -> str | None:
  if "mici" not in read(MODEL):
    return "not a comma 4"
  if os.path.exists(os.path.join(DIR, "disable")):
    return "disabled"
  if read(STAMP) == key:
    return "up to date"
  if fails(key) >= MAX_FAILS:
    return f"gave up after {MAX_FAILS} failed runs, rm {FAILS} to retry"
  return None


def fails(key: str) -> int:
  f = read(FAILS).split()
  return int(f[1]) if len(f) == 2 and f[0] == key and f[1].isdigit() else 0


def put(path: str, text: str):
  with open(path + ".tmp", "w") as f:
    f.write(text)
  os.replace(path + ".tmp", path)


def progress(line: str, cur: int) -> int:
  # overall bar: steps 1-3 share 0-20%, then the kernel step's own percent fills the rest
  if m := STEP.match(line):
    n, total = int(m.group(1)), int(m.group(2))
    return max(cur, 20 * (n - 1) // (total - 1))
  if m := KPCT.match(line):
    return max(cur, 20 + int(m.group(1)) * 80 // 100)
  return cur


def install(spinner, log) -> int:
  env = dict(os.environ, DPB_REBOOT="true")  # the reboot, if any, is ours, after the stamp logic
  cmd = ["bash", INSTALL, "--yes"]
  spinner.update_progress(0, 100)
  kernel_step = threading.Event()
  done = threading.Event()

  # output goes to a file, not a pipe: if boot.py stops waiting, the installer never writes to a closed pipe
  def pump():
    pct, buf = 0, ""
    with open(OUT, errors="replace") as f:
      while True:
        chunk = f.read()
        buf += chunk
        *lines, buf = buf.split("\n")
        for ln in lines:
          if ln.startswith("[4/4]"):
            kernel_step.set()
          log.write(ln + "\n")
          pct = progress(ln, pct)
          spinner.update_progress(pct, 100)
        if not chunk:
          if done.is_set():
            return
          time.sleep(0.1)

  try:
    with open(OUT, "w") as out:
      p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                           start_new_session=True)
  except OSError as e:
    log.write(f"{e!r}\n")
    return 1
  t = threading.Thread(target=pump, daemon=True)
  t.start()
  # steps 1-3: TIMEOUT_S, then killed. The kernel step is never killed: after KERNEL_WAIT_S boot.py only stops
  # waiting and lets manager start; the flash goes on in its own session
  end = time.monotonic() + TIMEOUT_S
  kend = None
  rc = None
  while rc is None:
    if kernel_step.is_set():
      kend = kend or time.monotonic() + KERNEL_WAIT_S
      if time.monotonic() > kend:
        break
    elif time.monotonic() > end:
      break
    try:
      rc = p.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
      pass
  if rc is None and not kernel_step.is_set():
    os.killpg(p.pid, signal.SIGTERM)  # lets the installer's EXIT trap tear apt down
    try:
      p.wait(timeout=10)
    except subprocess.TimeoutExpired:
      os.killpg(p.pid, signal.SIGKILL)
      p.wait()
    rc = 124
  time.sleep(0.2)
  done.set()
  t.join(timeout=5)
  if rc is None:
    log.write(f"kernel step still running after {KERNEL_WAIT_S:.0f} s, not waiting (output: {OUT})\n")
    return STILL
  if rc == 124:
    log.write(f"timed out after {TIMEOUT_S:.0f} s\n")
  return rc


def kernel_state() -> str:
  try:
    out = subprocess.run([*SUDO, "bash", KERNEL, "status"], capture_output=True, text=True,
                         timeout=120).stdout
  except (OSError, subprocess.SubprocessError):
    return ""
  return next((ln[6:] for ln in out.splitlines() if ln.startswith("state=")), "")


def main(spinner_factory=None) -> int:
  key = setup_key()
  why = skip_reason(key)
  if why is not None:
    print(f"dpbridge boot: skip, {why}")
    return 0
  if spinner_factory is None:
    from openpilot.common.spinner import Spinner as spinner_factory
  os.makedirs(STATE, exist_ok=True)
  with open(LOG, "a", buffering=1) as log:
    log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} key {key[:12]}\n")
    spinner = spinner_factory()
    try:
      rc = install(spinner, log)
    finally:
      spinner.close()
    if rc == STILL:
      # no stamp, no fail count: the next boot records how the flash went
      print("dpbridge boot: kernel step still running, starting openpilot")
      return 0
    if rc != 0:
      n = fails(key) + 1
      put(FAILS, f"{key} {n}")
      log.write(f"install failed ({rc}, {n}/{MAX_FAILS}), openpilot starts anyway, next boot tries again\n")
      print(f"dpbridge boot: install failed ({rc}), see {LOG}")
      return 0
    if kernel_state() == "pending":
      # flashed: the one reboot, no stamp (the new slot changes the key, so the next boot records the result)
      log.write("flashed, rebooting\n")
      log.flush()
      subprocess.run(REBOOT)
      return 0
    put(STAMP, key)
    if os.path.exists(FAILS):
      os.unlink(FAILS)
    log.write("done\n")
  return 0


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception as e:  # never stop openpilot from starting
    print(f"dpbridge boot: {e!r}")
    sys.exit(0)
