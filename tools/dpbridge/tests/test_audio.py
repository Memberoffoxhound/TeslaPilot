# audio.sh links the shared dmix config into place and takes it out again, never touching a foreign asound.conf.
import os
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]


def audio(tmp_path, *args):
  env = dict(os.environ, DPB_DIR=str(tmp_path), DPB_ETC=str(tmp_path / 'etc_asound.conf'), SUDO='')
  return subprocess.run(['bash', str(HERE / 'audio.sh'), *args], env=env, capture_output=True, text=True)


def test_on_then_off(tmp_path):
  (tmp_path / 'asound.conf').write_text('x')
  etc = tmp_path / 'etc_asound.conf'
  r = audio(tmp_path, 'on')
  assert r.returncode == 0, r.stderr
  assert etc.is_symlink() and os.readlink(etc) == str(tmp_path / 'asound.conf')
  assert audio(tmp_path, 'on').returncode == 0  # again is fine
  assert audio(tmp_path, 'off').returncode == 0 and not etc.exists()
  assert audio(tmp_path, 'off').returncode == 0


def test_refuses_without_config_and_leaves_foreign_files(tmp_path):
  r = audio(tmp_path, 'on')
  assert r.returncode != 0 and 'run deliver.sh push' in r.stderr
  (tmp_path / 'asound.conf').write_text('x')
  etc = tmp_path / 'etc_asound.conf'
  etc.write_text('someone else')
  r = audio(tmp_path, 'on')
  assert r.returncode != 0 and 'not ours' in r.stderr
  assert audio(tmp_path, 'off').returncode == 0 and etc.read_text() == 'someone else'


@pytest.mark.parametrize('title', ['python -m openpilot.selfdrive.ui.soundd', 'python -m openpilot.system.micd'])
def test_refuses_changes_while_soundd_or_micd_runs(tmp_path, title):
  (tmp_path / 'asound.conf').write_text('x')
  etc = tmp_path / 'etc_asound.conf'
  # a stand-in process with the daemon's command line
  p = subprocess.Popen(['bash', '-c', f'exec -a "{title}" sleep 30'])
  try:
    assert audio(tmp_path, 'off').returncode == 0  # already off: nothing to change, no refusal
    r = audio(tmp_path, 'on')
    assert r.returncode != 0 and 'turn the car off' in r.stderr and not etc.exists()
    etc.symlink_to(tmp_path / 'asound.conf')
    assert audio(tmp_path, 'on').returncode == 0  # already on
    r = audio(tmp_path, 'off')
    assert r.returncode != 0 and 'turn the car off' in r.stderr and etc.is_symlink()
  finally:
    p.kill()


def test_usage():
  r = subprocess.run(['bash', str(HERE / 'audio.sh')], capture_output=True, text=True)
  assert r.returncode == 2
