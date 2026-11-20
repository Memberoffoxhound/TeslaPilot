# chestnut: compile the pick's ONNX for our tinygrad, offroad only (modelmanagerd runs offroad)
from __future__ import annotations

import ctypes
import os
import pty
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.modeld.helpers import chestnut_pick, chestnut_present, compiled_dir, compiled_ready, tinygrad_ref
from openpilot.selfdrive.modelmanager import CHESTNUT_FAILED as FAILED, CHESTNUT_PROGRESS as PROGRESS, store

ROOT = Path(__file__).resolve().parents[3]
# tracks upstream's chestnut compile: its tinygrad flags, its compile_onnx.py args, PYTHONPATH and taskset
FLAGS = {'DEBUG': '1', 'DEV': 'USB+AMD:LLVM', 'FRAME_DEV': 'CPU', 'FLOAT16': '1', 'JIT_BATCH_SIZE': '0', 'GMMU': '0',
         'TC_OPT': '2', 'TC_MIN_GLOBALS': '32'}


CORES = '0-7'


def compile_env() -> dict[str, str]:
  # compile_onnx.py imports examples.openpilot from tinygrad_repo, as SConscript's PYTHONPATH gives it
  path = os.pathsep.join(p for p in (str(ROOT / 'tinygrad_repo'), os.environ.get('PYTHONPATH', '')) if p)
  return {**os.environ, **FLAGS, 'PYTHONPATH': path}


def compile_cmd(onnx: Path, pkl: Path) -> list[str]:
  # 0-7 as upstream (#38656); cores 4-7 are offline offroad, so a single big core fails
  return ['taskset', '-c', CORES, sys.executable, str(ROOT / 'tinygrad_repo/examples/openpilot/compile_onnx.py'), str(onnx), str(pkl),
          '--out-of-band', '--benchmark-runs', '1']


def fetch_onnx(ref: str, dest: Path, progress, should_stop) -> Path:
  from jetlink.registry.index import RegistryError, fetch_index
  from jetlink.registry.lfs import LFS_ENDPOINTS, lfs_download, lfs_hrefs
  pointer = fetch_index()[1].pointer(ref)
  if pointer is None:
    raise RegistryError("the model index has no ONNX for it")
  for _, href in lfs_hrefs(LFS_ENDPOINTS, pointer):
    return lfs_download(href, pointer, dest, progress=progress, should_stop=should_stop)
  raise RegistryError("no server has its ONNX")


_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
_BAR = re.compile(r'^compiling\b.*?(\d+)/(\d+) \[')
_BENCH = re.compile(r'^\[(\d+)/(\d+)\] [\d.]+ ms')
_VERIFY = re.compile(r'^opened device DISK:\S+\.pkl ')  # the ONNX opens DISK too
# compile_onnx.py's DEBUG=1 output, in order, to (frac, msg); kernels fill 0.05 to 0.80
KERNELS = (0.05, 0.80)


def parse_line(line: str) -> tuple[float, str] | None:
  line = _ANSI.sub('', line).strip()
  if m := _BAR.match(line):
    n, t = int(m[1]), int(m[2])
    return KERNELS[0] + (KERNELS[1] - KERNELS[0]) * (n / t if t else 0.0), "compiling"
  if line.startswith('scheduled '):
    return KERNELS[0], "scheduling"
  if line.startswith('JIT captured'):
    return 0.85, "checking"
  if m := _BENCH.match(line):
    return (0.90, "saving") if int(m[1]) + 1 >= int(m[2]) else (0.88, "benchmarking")
  if _VERIFY.match(line):
    return 0.95, "verifying"
  return None


def last_line(tail: bytes) -> str:
  lines = [_ANSI.sub('', ln).strip() for ln in re.split(r'[\r\n]+', tail.decode(errors='replace'))]
  return next((ln for ln in reversed(lines) if ln), "")[-200:]


def _die_with_parent():
  ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG: never hold the GPU past modelmanagerd


class ChestnutCompiler:
  def __init__(self, present=chestnut_present, fetch=fetch_onnx, popen=subprocess.Popen, log=None):
    self.present = present
    self.fetch = fetch
    self.popen = popen
    self.log = log or cloudlog
    self.ref: str | None = None
    self._thread: threading.Thread | None = None
    self._proc = None
    self._stop = threading.Event()
    self._last: dict | None = None

  def busy(self) -> bool:
    return self._thread is not None and self._thread.is_alive()

  def step(self, mode: str) -> None:
    want = mode == 'chestnut' and self.present()
    ref = chestnut_pick(store)
    if self.busy():
      if not want or ref != self.ref:
        self.stop()
      return
    if not want or not ref or compiled_ready(ref) or store.get(FAILED) == ref:
      return
    self.ref = ref
    self._stop.clear()
    self._thread = threading.Thread(target=self._run, args=(ref,), daemon=True)
    self._thread.start()

  def stop(self) -> None:
    self._stop.set()
    if self._proc is not None and self._proc.poll() is None:
      try:
        os.killpg(self._proc.pid, signal.SIGKILL)  # tinygrad's compile workers too
      except (OSError, TypeError):
        pass
      self._proc.kill()

  def _progress(self, ref, stage, frac=0.0, msg=""):  # jetlink.progress's shape
    p = {'ref': ref, 'stage': stage, 'frac': round(frac, 2), 'msg': msg}
    if p != self._last:
      self._last = p
      store.put(PROGRESS, p)

  def _compile(self, ref: str, onnx: Path, pkl: Path) -> None:
    # a pty so tinygrad prints its live tqdm bars and flushes each line
    master, slave = pty.openpty()
    try:
      self._proc = self.popen(compile_cmd(onnx, pkl), env=compile_env(), cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=slave,
                              stderr=slave, preexec_fn=_die_with_parent, start_new_session=True)
    finally:
      os.close(slave)
    if self._stop.is_set():
      self.stop()  # stopped while it spawned
    frac, buf, tail = 0.0, b'', b''
    try:
      while True:
        try:
          chunk = os.read(master, 4096)
        except OSError:  # EIO once the child side is gone
          chunk = b''
        if not chunk:
          break
        tail = (tail + chunk)[-4096:]
        *lines, buf = re.split(rb'[\r\n]', buf + chunk)
        for ln in lines:
          step = parse_line(ln.decode(errors='replace'))
          if step and step[0] >= frac:
            frac = step[0]
            self._progress(ref, 'compiling', frac, step[1])
    finally:
      os.close(master)
    rc = self._proc.wait()
    if self._stop.is_set():
      raise InterruptedError("stopped")
    if rc:
      self.log.warning(f"chestnut: compile exited {rc}: {tail[-500:].decode(errors='replace')}")
      raise RuntimeError(last_line(tail) or f"compile exited {rc}")

  def _run(self, ref: str) -> None:
    d = compiled_dir(ref)
    onnx, pkl, stamp = d / 'model.onnx', d / 'driving_tinygrad.pkl', d / 'tinygrad_ref'
    self._last = None
    try:
      stamp.unlink(missing_ok=True)
      if not onnx.is_file():
        self._progress(ref, 'downloading', 0.0, "downloading")
        self.fetch(ref, onnx, lambda f: self._progress(ref, 'downloading', f, "downloading"), self._stop.is_set)
      self._progress(ref, 'compiling', 0.0, "loading model")
      self.log.warning(f"chestnut: compiling {ref[:10]}")
      self._compile(ref, onnx, pkl)
      stamp.write_text(tinygrad_ref())
      onnx.unlink(missing_ok=True)
      store.remove(FAILED)
      self._progress(ref, 'ready', 1.0)
      self.log.warning(f"chestnut: {ref[:10]} ready")
    except Exception as e:
      if self._stop.is_set():
        store.remove(PROGRESS)
        return
      self.log.exception(f"chestnut: compiling {ref[:10]} failed")
      store.put(FAILED, ref)
      self._progress(ref, 'failed', 0.0, f"failed: {e}"[:60].lower())
