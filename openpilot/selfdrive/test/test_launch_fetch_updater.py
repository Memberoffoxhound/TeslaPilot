"""TeslaPilot: launch pulls the LFS updater before the AGNOS flash loop."""
import subprocess
from pathlib import Path

import pytest

from openpilot.common.basedir import BASEDIR

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
