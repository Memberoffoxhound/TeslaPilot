# audio.sh only takes out the old shared-dmix link, never a foreign asound.conf.
import os
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]


def audio(tmp_path, *args):
  env = dict(os.environ, DPB_DIR=str(tmp_path), DPB_ETC=str(tmp_path / 'etc_asound.conf'), SUDO='')
  return subprocess.run(['bash', str(HERE / 'audio.sh'), *args], env=env, capture_output=True, text=True)


def test_off_removes_our_link_only(tmp_path):
  etc = tmp_path / 'etc_asound.conf'
  etc.symlink_to(tmp_path / 'asound.conf')
  assert audio(tmp_path, 'off').returncode == 0 and not etc.is_symlink()
  assert audio(tmp_path, 'off').returncode == 0
  etc.write_text('someone else')
  assert audio(tmp_path, 'off').returncode == 0 and etc.read_text() == 'someone else'


def test_on_is_gone(tmp_path):
  r = audio(tmp_path, 'on')
  assert r.returncode == 2 and 'gone' in r.stderr and not (tmp_path / 'etc_asound.conf').exists()


@pytest.mark.parametrize('title', ['python -m openpilot.selfdrive.ui.soundd', 'python -m openpilot.system.micd'])
def test_refuses_while_soundd_or_micd_runs(tmp_path, title):
  etc = tmp_path / 'etc_asound.conf'
  p = subprocess.Popen(['bash', '-c', f'exec -a "{title}" sleep 30'])
  try:
    assert audio(tmp_path, 'off').returncode == 0  # nothing to remove, no refusal
    etc.symlink_to(tmp_path / 'asound.conf')
    r = audio(tmp_path, 'off')
    assert r.returncode != 0 and 'turn the car off' in r.stderr and etc.is_symlink()
  finally:
    p.kill()


def test_usage():
  r = subprocess.run(['bash', str(HERE / 'audio.sh')], capture_output=True, text=True)
  assert r.returncode == 2
