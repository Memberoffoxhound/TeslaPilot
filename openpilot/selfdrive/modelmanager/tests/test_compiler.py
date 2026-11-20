import os
import sys
from pathlib import Path
import threading
from unittest import mock

import pytest

from openpilot.selfdrive import modelmanager as mm
from openpilot.selfdrive.modeld import helpers
from openpilot.selfdrive.modelmanager import compiler as cc
from openpilot.selfdrive.modelmanager import store

REF = 'a' * 40


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'p'))
  monkeypatch.delenv('OPENPILOT_PREFIX', raising=False)
  store._store.clear()
  monkeypatch.setattr(store, '_params', mock.Mock(side_effect=ImportError('no params_pyx')))
  monkeypatch.setattr(helpers, 'CHESTNUT_DIR', tmp_path / 'models')
  monkeypatch.setattr(helpers, 'tinygrad_ref', lambda: 'tg1')
  monkeypatch.setattr(cc, 'tinygrad_ref', lambda: 'tg1')
  store.put(mm.CHESTNUT_PICK, {'ref': REF, 'displayName': 'Alpha'})


class Proc:
  pid = None

  def __init__(self, rc=0, gate=None):
    self.returncode, self.gate, self.killed = rc, gate, False

  def wait(self):
    if self.gate:
      self.gate.wait(5)
    return self.returncode

  def poll(self):
    return None

  def kill(self):
    self.killed = True
    self.gate.set()


# tinygrad's DEBUG=1 output over a pty, cut down from a real chestnut compile
SAMPLE = b"".join([
  b"opened device DISK:/data/models/chestnut/x/model.onnx from pid:1\n",
  b"opened device USB+AMD from pid:1\n",
  b"scheduled  1093 kernels in 24348.12 ms\n",
  b"\rcompiling E_4: \x1b[0m  0%|          | 0/77 [00:00<?, ?it/s]",
  b"\rcompiling r_32_16:  52%|#####     | 40/77 [00:30<00:27, 1.34it/s]",
  b"\rcompiling r_32_16: 100%|##########| 77/77 [00:57<00:00, 1.34it/s]\n",
  b"scheduled   485 kernels in 9000.00 ms\n",
  b"JIT captured 2 linears with 12 inputs\n",
  b"  [0/1] 26.46 ms\n",
  b"opened device DISK:/data/models/chestnut/x/driving_tinygrad.pkl from pid:1\n",
])


def rig(rc=0, gate=None, fetch=None, out=b''):
  procs = []

  def popen(cmd, **kw):
    procs.append(Proc(rc, gate))
    os.write(kw['stdout'], out)
    helpers.compiled_dir(REF).joinpath('driving_tinygrad.pkl').write_bytes(b'pkl')
    return procs[-1]

  def default_fetch(ref, dest, progress, stop):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b'onnx')
    progress(1.0)

  return cc.ChestnutCompiler(present=lambda: True, fetch=fetch or default_fetch, popen=popen, log=mock.Mock()), procs


def run(c, mode='chestnut'):
  c.step(mode)
  if c._thread:
    c._thread.join(5)


def test_compiles_the_pick_offroad():
  c, procs = rig()
  run(c)
  assert helpers.compiled_ready(REF) and store.get(mm.CHESTNUT_PROGRESS)['stage'] == 'ready'
  assert not helpers.compiled_dir(REF).joinpath('model.onnx').exists()
  run(c)
  assert len(procs) == 1  # ready: nothing more to do


def test_only_with_a_chestnut():
  c, procs = rig()
  run(c, mode='jetlink')
  c.present = lambda: False
  run(c)
  assert procs == [] and store.get(mm.CHESTNUT_PROGRESS) is None


def test_failure_marks_failed_and_waits_for_a_new_pick():
  c, procs = rig(rc=1)
  run(c)
  assert store.get(mm.CHESTNUT_FAILED) == REF and store.get(mm.CHESTNUT_PROGRESS)['stage'] == 'failed'
  assert not helpers.compiled_ready(REF)
  run(c)
  assert len(procs) == 1


def test_fetch_failure_is_failed():
  def fetch(*a):
    raise OSError('offline')
  c, procs = rig(fetch=fetch)
  run(c)
  assert procs == [] and store.get(mm.CHESTNUT_FAILED) == REF


def test_unplug_stops_the_compile():
  gate = threading.Event()
  c, procs = rig(gate=gate)
  c.step('chestnut')
  for _ in range(100):
    if procs:
      break
    threading.Event().wait(0.01)
  c.step('none')
  c._thread.join(5)
  assert procs[0].killed and store.get(mm.CHESTNUT_PROGRESS) is None and store.get(mm.CHESTNUT_FAILED) is None


def test_compile_cmd_uses_our_tinygrad():
  cmd = cc.compile_cmd('m.onnx', 'm.pkl')
  assert cmd[4].endswith('tinygrad_repo/examples/openpilot/compile_onnx.py') and '--out-of-band' in cmd
  assert cc.FLAGS['DEV'] == 'USB+AMD:LLVM'


def test_compile_cmd_flags_exist_in_compile_onnx():
  # every option we pass must be one the pinned compile_onnx.py accepts
  cmd = cc.compile_cmd('m.onnx', 'm.pkl')
  src = Path(cmd[4]).read_text()
  for arg in (a for a in cmd if a.startswith('--')):
    assert f"'{arg}'" in src, arg


def test_compile_env_has_tinygrad_repo_first(monkeypatch):
  monkeypatch.setenv('PYTHONPATH', '/x')
  env = cc.compile_env()
  assert env['PYTHONPATH'].split(':') == [str(cc.ROOT / 'tinygrad_repo'), '/x']
  assert Path(env['PYTHONPATH'].split(':')[0], 'examples/openpilot/compile_onnx.py').is_file()
  assert all(env[k] == v for k, v in cc.FLAGS.items())


def test_compile_env_without_pythonpath(monkeypatch):
  monkeypatch.delenv('PYTHONPATH', raising=False)
  assert cc.compile_env()['PYTHONPATH'] == str(cc.ROOT / 'tinygrad_repo')


def test_taskset_includes_an_always_online_core():
  cmd = cc.compile_cmd('m.onnx', 'm.pkl')
  assert cmd[:3] == ['taskset', '-c', '0-7']
  lo, hi = map(int, cmd[2].split('-'))
  assert lo == 0 and hi == 7  # cpu0 is never offline


def test_popen_gets_compile_env():
  seen = {}
  c, procs = rig()
  inner = c.popen
  def popen(cmd, **kw):
    seen.update(kw)
    return inner(cmd, **kw)
  c.popen = popen
  run(c)
  assert seen['env']['PYTHONPATH'].startswith(str(cc.ROOT / 'tinygrad_repo')) and seen['cwd'] == str(cc.ROOT)


def test_parse_line_maps_tinygrad_output():
  assert cc.parse_line('scheduled  1093 kernels in 24348.12 ms') == (0.05, 'scheduling')
  assert cc.parse_line('compiling r_32_16:  52%|#####     | 40/77 [00:30<00:27, 1.34it/s]') == (pytest.approx(0.05 + 0.75 * 40 / 77), 'compiling')
  assert cc.parse_line('\x1b[0mcompiling E_4: 100%|#| 77/77 [00:57<00:00, 1.34it/s]') == (0.80, 'compiling')
  assert cc.parse_line('JIT captured 2 linears with 12 inputs') == (0.85, 'checking')
  assert cc.parse_line('  [0/20] 26.46 ms') == (0.88, 'benchmarking')
  assert cc.parse_line('  [0/1] 26.46 ms') == (0.90, 'saving')
  assert cc.parse_line('opened device DISK:/x.pkl from pid:1') == (0.95, 'verifying')
  assert cc.parse_line('opened device USB+AMD from pid:1') is None
  assert cc.parse_line('opened device DISK:/data/x/model.onnx from pid:1') is None
  assert cc.parse_line('') is None


def test_progress_follows_the_compile_and_never_goes_back():
  seen = []
  c, procs = rig(out=SAMPLE)
  real = store.put
  with mock.patch.object(store, 'put', side_effect=lambda k, v: (seen.append(dict(v)) if k == mm.CHESTNUT_PROGRESS else None, real(k, v))):
    run(c)
  comp = [(p['frac'], p['msg']) for p in seen if p['stage'] == 'compiling']
  assert comp[0] == (0.0, 'loading model')
  assert [m for _, m in comp] == ['loading model', 'scheduling', 'compiling', 'compiling', 'compiling', 'checking', 'saving', 'verifying']
  assert [f for f, _ in comp] == sorted(f for f, _ in comp)
  assert seen[-1] == {'ref': REF, 'stage': 'ready', 'frac': 1.0, 'msg': ''}


def test_failure_shows_the_last_error_line():
  out = b"Traceback (most recent call last):\r\n  File \"compile_onnx.py\", line 10\r\nModuleNotFoundError: No module named 'examples'\r\n"
  c, procs = rig(rc=1, out=out)
  run(c)
  p = store.get(mm.CHESTNUT_PROGRESS)
  assert p['stage'] == 'failed' and p['msg'] == "failed: modulenotfounderror: no module named 'examples'"


def test_last_line_strips_tqdm_and_ansi():
  assert cc.last_line(b"\rcompiling: 10%\r\x1b[31mboom\x1b[0m\r\n\n") == 'boom'
  assert cc.last_line(b'') == ''


def test_popen_runs_in_its_own_session_on_a_pty():
  seen = {}
  c, procs = rig()
  inner = c.popen
  def popen(cmd, **kw):
    seen.update(kw)
    assert os.isatty(kw['stdout']) and kw['stdout'] == kw['stderr']
    return inner(cmd, **kw)
  c.popen = popen
  run(c)
  assert seen['start_new_session'] is True


def test_real_child_output_reaches_progress(tmp_path):
  # a real process on the pty, printing like compile_onnx.py
  script = "import sys;print('scheduled 9 kernels in 1 ms');sys.stderr.write('\\rcompiling a: 50%| 1/2 [');sys.stderr.flush()"
  c, _ = rig()
  c.popen = lambda cmd, **kw: __import__('subprocess').Popen([sys.executable, '-c', script], **{**kw, 'preexec_fn': None})
  helpers.compiled_dir(REF).mkdir(parents=True, exist_ok=True)
  helpers.compiled_dir(REF).joinpath('driving_tinygrad.pkl').write_bytes(b'pkl')
  msgs = []
  real = store.put
  with mock.patch.object(store, 'put', side_effect=lambda k, v: (msgs.append(v.get('msg')) if k == mm.CHESTNUT_PROGRESS else None, real(k, v))):
    run(c)
  assert 'scheduling' in msgs and store.get(mm.CHESTNUT_PROGRESS)['stage'] == 'ready'
