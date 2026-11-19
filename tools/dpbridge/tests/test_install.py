# install_userspace.sh's EXIT trap, run as the script runs it (set -euo pipefail, --yes) with a stub sudo.
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def test_trap_tears_down_apt_after_a_good_install(tmp_path):
  trap = next(ln for ln in (HERE / 'install_userspace.sh').read_text().splitlines() if re.match(r"trap '.*' EXIT$", ln))
  stub = tmp_path / 'sudo'
  # the success path already unmounted, so umount fails here like it does on the comma
  stub.write_text('#!/bin/bash\ncase $1 in umount) exit 32 ;; */apt_teardown.sh) echo teardown ;; esac\n')
  stub.chmod(0o755)
  r = subprocess.run(['bash', '-c', f'set -euo pipefail; YES=1; MNT={tmp_path}/mnt; SUDO={stub}\n{trap}\necho installed'],
                     capture_output=True, text=True)
  assert r.returncode == 0 and r.stdout.split() == ['installed', 'teardown'], (r.returncode, r.stdout, r.stderr)


def test_radio_helper_is_installed_and_enabled():
  text = (HERE / 'install_userspace.sh').read_text()
  assert 'Experimental = true' in text
  assert 'dpbridge-radio.service' in text
  assert 'systemctl enable dpbridge-radio.service' in text
  assert 'systemctl disable bluetooth.service bluealsa.service bluealsa-aplay.service' in text
  assert 'radio.sh' in text
