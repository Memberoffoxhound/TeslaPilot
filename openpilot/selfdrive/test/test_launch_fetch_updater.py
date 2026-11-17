"""TeslaPilot: launch pulls the LFS updater before the AGNOS flash loop."""
import subprocess
from pathlib import Path

import pytest

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.modeld import accel_keys

LAUNCH = Path(BASEDIR) / 'launch_chffrplus.sh'
UPDATER = 'openpilot/common/hardware/comma/updater'
POINTER = b'version https://git-lfs.github.com/spec/v1\noid sha256:' + b'0' * 64 + b'\nsize 12345\n'
ELF = b'\x7fELF real updater'


def _run(tmp_path, updater, fails=0):
  (tmp_path / UPDATER).parent.mkdir(parents=True)
  (tmp_path / UPDATER).write_bytes(updater)
  lfs = tmp_path / 'tools/lfs.sh'
  lfs.parent.mkdir()
  # stub: count calls, fail `fails` times, then write the real file
  lfs.write_text('#!/usr/bin/env bash\necho x >> "$(dirname "$0")/calls"\n' +
                 f'[ $(wc -l < "$(dirname "$0")/calls") -le {fails} ] && exit 1\n' +
                 f'printf "\\177ELF real updater" > "$(dirname "$0")/../{UPDATER}"\n')
  lfs.chmod(0o755)
  script = f'DIR={tmp_path}; sleep() {{ echo "$1" >> {tmp_path}/sleeps; }}\n' + \
           subprocess.check_output(['sed', '-n', '/^function fetch_updater {/,/^}/p', LAUNCH], text=True) + 'fetch_updater\n'
  subprocess.run(['bash', '-c', script], check=True, timeout=10, capture_output=True)
  calls = (tmp_path / 'tools/calls').read_text().count('x') if (tmp_path / 'tools/calls').exists() else 0
  sleeps = (tmp_path / 'sleeps').read_text().split() if (tmp_path / 'sleeps').exists() else []
  return calls, sleeps


def test_real_updater_is_a_noop(tmp_path):
  assert _run(tmp_path, ELF) == (0, [])


@pytest.mark.parametrize('fails', [0, 3])
def test_pointer_pulls_until_real(tmp_path, fails):
  calls, sleeps = _run(tmp_path, POINTER, fails)
  assert calls == fails + 1
  assert sleeps == ['0'] + ['10'] * fails
  assert (tmp_path / UPDATER).read_bytes().startswith(b'\x7fELF')


def test_guard_runs_before_the_flash_loop():
  s = LAUNCH.read_text()
  i = s.index('fetch_updater\n    while true; do')
  assert s.index('--verify "$MANIFEST"') < i < s.index('"$DIR/openpilot/common/hardware/comma/updater" "$AGNOS_PY"')


def test_updater_pull_skips_the_big_model():
  # the updater must not wait on fetch_big_model's 767 MB
  s = LAUNCH.read_text()
  assert '"$DIR/tools/lfs.sh" pull --exclude "$BIG_MODEL"' in s
  assert 'BIG_MODEL="openpilot/selfdrive/modeld/models/big_driving_tinygrad.pkl"' in s
  assert f'BIG_MODEL="{accel_keys.BIG_MODEL}"' in s
  assert s.index('fetch_big_model &') < s.index('    agnos_init\n')
  assert 'scripts/fetch_big_model.py' in s


def _fetch_big(tmp_path, devices, fails=0):
  # devices: AcceleratorDevice before each loop pass; the stub fetch writes the real file
  pkl = tmp_path / 'openpilot/selfdrive/modeld/models/big_driving_tinygrad.pkl'
  pkl.parent.mkdir(parents=True)
  pkl.write_bytes(POINTER)
  (tmp_path / 'scripts').mkdir()
  fetch = tmp_path / 'scripts/fetch_big_model.py'
  fetch.write_text(f'#!/usr/bin/env bash\necho x >> {tmp_path}/calls\n[ $(wc -l < {tmp_path}/calls) -le {fails} ] && exit 1\nprintf real > {pkl}\n')
  fetch.chmod(0o755)
  (tmp_path / 'devices').write_text('\n'.join(devices) + '\n')
  fn = subprocess.check_output(['sed', '-n', '/^function fetch_big_model {/,/^}/p', LAUNCH], text=True)
  fn = fn.replace('/data/params/d/AcceleratorDevice', f'{tmp_path}/dev')
  # each sleep advances to the next device reading; out of readings ends the run
  script = (f'DIR={tmp_path}; BIG_MODEL=openpilot/selfdrive/modeld/models/big_driving_tinygrad.pkl; n=0\n' +
            f'sleep() {{ echo "$1" >> {tmp_path}/sleeps; n=$((n+1)); l=$(sed -n "${{n}}p" {tmp_path}/devices); ' +
            f'[ -z "$l" ] && exit 0; [ "$l" = "-" ] && rm -f {tmp_path}/dev || printf %s "$l" > {tmp_path}/dev; }}\n') + fn + 'fetch_big_model\n'
  subprocess.run(['bash', '-c', script], check=True, timeout=10, capture_output=True)
  calls = (tmp_path / 'calls').read_text().count('x') if (tmp_path / 'calls').exists() else 0
  return calls, (tmp_path / 'sleeps').read_text().split(), pkl.read_bytes() == b'real'


def test_big_model_waits_for_an_accelerator(tmp_path):
  assert _fetch_big(tmp_path, ['-', 'none', 'none']) == (0, ['0', '10', '10', '10'], False)


@pytest.mark.parametrize('device', ['chestnut', 'jetlink-usb', 'jetlink-ios'])
def test_big_model_starts_once_seen(tmp_path, device):
  assert _fetch_big(tmp_path, ['none', device]) == (1, ['0', '10'], True)


def test_big_model_failed_pull_backs_off(tmp_path):
  assert _fetch_big(tmp_path, ['chestnut'] * 3, fails=1) == (2, ['0', '60'], True)
