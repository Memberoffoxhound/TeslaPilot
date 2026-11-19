#!/usr/bin/env python3
import json
import os
import subprocess
import time
from pathlib import Path

# Automatic kernel flash on a fresh install or after an AGNOS update, no menu. Offroad only, this
# runs tools/dpbridge/kernel.sh as root: pinned sha, AGNOS match, inactive slot only, read back,
# one reboot. A failed try is not repeated (kernel.sh keys it on image, AGNOS and slot).

STATE_PATH = "/dev/shm/dpbridge-kernel.json"
POLL_S = 10.0


def helper() -> str:
  from openpilot.common.basedir import BASEDIR
  return os.path.join(BASEDIR, "tools/dpbridge/kernel.sh")


def sh(args: list[str], timeout: float) -> tuple[int, str]:
  try:
    r = subprocess.run(["sudo", "bash", helper(), *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr
  except Exception as e:
    return 1, f"refusing: {e!r}"


def parse_status(text: str) -> dict:
  st: dict = {}
  for ln in text.splitlines():
    k, sep, v = ln.partition("=")
    if sep and k.isidentifier():
      st[k] = v.strip()
  return st


def last_error(out: str) -> str:
  for ln in reversed(out.splitlines()):
    if ln.startswith("refusing: "):
      return ln[len("refusing: "):]
  return "flash failed"


def should_flash(status: dict, onroad: bool) -> bool:
  return not onroad and status.get("state") == "offer"


def write_state(state: dict, path: str | None = None):
  dest = Path(STATE_PATH if path is None else path)
  dest.parent.mkdir(parents=True, exist_ok=True)
  tmp = dest.with_suffix(dest.suffix + ".tmp")
  tmp.write_text(json.dumps(state, separators=(",", ":")))
  os.replace(tmp, dest)


def read_state(path: str | None = None) -> dict:
  try:
    return json.loads(Path(STATE_PATH if path is None else path).read_text())
  except (OSError, ValueError):
    return {}


def step(run_sh, onroad: bool, prev: dict) -> dict:
  rc, out = run_sh(["status"], 30)
  st = parse_status(out) if rc == 0 else {"state": "error"}
  if prev.get("phase") == "failed":
    # one try per process; kernel.sh also refuses to repeat it after a restart
    return dict(st, phase="failed", error=prev.get("error", ""))
  st["phase"] = "idle"
  if should_flash(st, onroad):
    write_state(dict(st, phase="flashing"))
    rc, out = run_sh(["flash", "--yes"], 1800)
    if rc != 0:
      st.update(phase="failed", error=last_error(out))
    # on success kernel.sh reboots
  return st


def main():
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog
  params = Params()
  # after the one reboot: record the result and install the Bluetooth userspace
  rc, out = sh(["post-boot", "--yes"], 900)
  if rc != 0:
    cloudlog.warning(f"dpb kerneld: post-boot failed, {out[-400:]}")
  prev: dict = {}
  while True:
    try:
      onroad = params.get_bool("IsOnroad")
      st = step(sh, onroad, prev)
      if st != prev:
        write_state(st)
      prev = st
    except Exception as e:
      cloudlog.warning(f"dpb kerneld: {e!r}")
    time.sleep(POLL_S)


if __name__ == "__main__":
  main()
