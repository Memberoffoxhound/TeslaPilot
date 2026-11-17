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
  def __init__(self, rc=0, gate=None):
    self.returncode, self.gate, self.killed = rc, gate, False

  def communicate(self):
    if self.gate:
      self.gate.wait(5)
    return b'', b'boom'

  def poll(self):
    return None

  def kill(self):
    self.killed = True
    self.gate.set()


def rig(rc=0, gate=None, fetch=None):
  procs = []

  def popen(cmd, **kw):
    procs.append(Proc(rc, gate))
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
