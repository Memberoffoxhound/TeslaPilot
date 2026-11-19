# install_userspace.sh's EXIT trap, run as the script runs it (set -euo pipefail, --yes) with a stub sudo.
import re
import signal
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]


def teardown_block():
  text = (HERE / 'install_userspace.sh').read_text()
  end = "trap 'exit 143' TERM INT HUP"
  return text[text.index('TORN=0'):text.index(end) + len(end)]


def stub_sudo(tmp_path):
  stub = tmp_path / 'sudo'
  # the success path already unmounted, so umount fails here like it does on the comma
  stub.write_text('#!/bin/bash\ncase $1 in umount) exit 32 ;; */apt_teardown.sh) echo teardown ;; esac\n')
  stub.chmod(0o755)
  return stub


def test_trap_tears_down_apt_after_a_good_install(tmp_path):
  stub = stub_sudo(tmp_path)
  r = subprocess.run(['bash', '-c', f'set -euo pipefail; YES=1; MNT={tmp_path}/mnt; SUDO={stub}\n{teardown_block()}\necho installed'],
                     capture_output=True, text=True)
  assert r.returncode == 0 and r.stdout.split() == ['installed', 'teardown'], (r.returncode, r.stdout, r.stderr)


def test_teardown_runs_once_before_the_kernel_step(tmp_path):
  stub = stub_sudo(tmp_path)
  script = f'set -euo pipefail; YES=1; MNT={tmp_path}/mnt; SUDO={stub}\n{teardown_block()}\nteardown; echo kernel; false'
  r = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
  assert r.returncode != 0 and r.stdout.split() == ['teardown', 'kernel'], r.stdout  # not again on the failing exit
  text = script_text()
  k = text[text.index('echo "[4/4] kernel"'):]
  assert k.index('teardown') < k.index('kernel_step') < k.index('$SUDO "$REBOOT"')


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_teardown_runs_on_a_signal(tmp_path, sig):
  # what boot.py's timeout sends: the installer must still put / back to read-only
  stub = stub_sudo(tmp_path)
  script = f'set -euo pipefail; YES=1; MNT={tmp_path}/mnt; SUDO={stub}\n{teardown_block()}\necho up; sleep 30 > /dev/null & wait'
  p = subprocess.Popen(['bash', '-c', script], stdout=subprocess.PIPE, text=True)
  assert p.stdout.readline().strip() == 'up'
  p.send_signal(sig)
  out, _ = p.communicate(timeout=10)
  assert p.returncode == 143 and out.split() == ['teardown']


def run_onroad_check(tmp_path, manager, offroad, yes=1):
  import os
  line = next(ln for ln in (HERE / 'install_userspace.sh').read_text().splitlines() if 'openpilot is onroad' in ln)
  b = tmp_path / 'bin'
  b.mkdir()
  (b / 'pgrep').write_text(f'#!/bin/sh\nexit {0 if manager else 1}\n')
  (b / 'pgrep').chmod(0o755)
  (tmp_path / 'p').mkdir()
  if offroad is not None:
    (tmp_path / 'p/IsOffroad').write_text(offroad)
  lib = (HERE / 'lib.sh').read_text()
  env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", DPB_PARAMS=str(tmp_path / 'p'))
  return subprocess.run(['bash', '-c', f'set -euo pipefail; YES={yes}\n{lib}\n{line}\necho go'], capture_output=True,
                        text=True, env=env)


@pytest.mark.parametrize('manager, offroad, yes, ok', [(True, '0', 1, False), (True, None, 1, False), (True, '1', 1, True),
                                                       (False, '0', 1, True), (True, '0', 0, True)])
def test_manual_install_refuses_onroad(tmp_path, manager, offroad, yes, ok):
  r = run_onroad_check(tmp_path, manager, offroad, yes)
  assert (r.returncode == 0 and r.stdout.strip() == 'go') == ok, (r.stdout, r.stderr)
  if not ok:
    assert 'openpilot is onroad' in r.stderr


@pytest.mark.parametrize('offroad, ok', [('0', False), ('1', True)])
def test_onroad_check_finds_the_real_manager(tmp_path, offroad, ok):
  # the real pgrep against a process started the way launch_chffrplus.sh starts it: cd .../system/manager; ./manager.py
  import os
  import sys
  import time
  line = next(ln for ln in (HERE / 'install_userspace.sh').read_text().splitlines() if 'openpilot is onroad' in ln)
  mgr = tmp_path / 'openpilot/system/manager'
  mgr.mkdir(parents=True)
  (mgr / 'manager.py').write_text(f'#!{sys.executable}\nimport time\ntime.sleep(30)\n')
  (mgr / 'manager.py').chmod(0o755)
  (tmp_path / 'p').mkdir()
  (tmp_path / 'p/IsOffroad').write_text(offroad)
  lib = (HERE / 'lib.sh').read_text()
  env = dict(os.environ, DPB_PARAMS=str(tmp_path / 'p'))
  script = f'set -euo pipefail; YES=1\n{lib}\n{line}\necho go'
  p = subprocess.Popen(['./manager.py'], cwd=mgr)
  try:
    time.sleep(0.3)
    cmd = open(f'/proc/{p.pid}/cmdline').read().replace('\0', ' ')
    assert cmd.endswith('./manager.py ') and 'system/manager/manager.py' not in cmd
    r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=env)
    assert (r.returncode == 0 and r.stdout.strip() == 'go') == ok, (r.stdout, r.stderr)
  finally:
    p.kill()
    p.wait()
  # no manager: passes, and the pattern does not match boot.py or this test
  r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=env)
  assert r.returncode == 0 and r.stdout.strip() == 'go', r.stderr


def test_onroad_check_is_before_any_change():
  text = script_text()
  assert text.index('openpilot is onroad') < text.index('echo "[1/4]')


def test_radio_helper_is_installed_and_enabled():
  text = (HERE / 'install_userspace.sh').read_text()
  assert 'Experimental = true' in text
  assert 'dpbridge-radio.service' in text
  assert 'systemctl enable dpbridge-radio.service' in text
  assert 'systemctl disable bluetooth.service bluealsa.service bluealsa-aplay.service' in text
  assert 'radio.sh' in text


def script_text():
  # without comment lines, so the rules below look at commands only
  return '\n'.join(ln for ln in (HERE / 'install_userspace.sh').read_text().splitlines() if not ln.lstrip().startswith('#'))


def env_file(name):
  return dict(ln.split('=', 1) for ln in (HERE / name).read_text().splitlines() if '=' in ln and not ln.startswith('#'))


def test_bluez_is_the_pinned_dpbridge_build():
  env = env_file('bluez/bluez.env')
  assert env['BLUEZ_VER'] == '5.83' and re.fullmatch(r'[0-9a-f]{64}', env['BLUEZ_SHA'])
  assert env['BLUEZ_URL'].startswith('https://github.com/Memberoffoxhound/TeslaPilot/releases/download/')
  assert env['BLUEZ_URL'].endswith('/' + env['BLUEZ_TAR'])
  # GPL: the source ships in the same release as the debs
  assert env['BLUEZ_SRC_URL'].rsplit('/', 1)[0] == env['BLUEZ_URL'].rsplit('/', 1)[0]
  assert env['BLUEZ_SRC_URL'].endswith(f"/bluez-{env['BLUEZ_VER']}.tar.xz")
  text = script_text()
  pkgs = re.search(r'^PKGS="([^"]*)"', text, re.M).group(1).split()
  assert 'bluez' not in pkgs and 'bluez-obexd' not in pkgs and 'libbluetooth3' not in pkgs
  assert 'bluez-alsa-utils' in pkgs


def test_install_rules():
  text = script_text()
  assert 'apt-get install' not in text and 'fix-broken' not in text and not re.search(r'\budev\b(?!s)', text.replace('--ignore-depends=udev', ''))
  assert '$SUDO dpkg --ignore-depends=udev --force-confold -i "$BZ"/*.deb "$DEBS"/apt/*.deb' in text
  assert 'ExecStart=/usr/libexec/bluetooth/bluetoothd -E' in text
  assert 'dpbridge-obex.service' in text and '/usr/libexec/bluetooth/obexd -n -s -P $OBEX_OFF' in text
  off = re.search(r'^OBEX_OFF=(\S+)', text, re.M).group(1).split(',')
  assert 'pbap' in off and 'bluetooth' not in off  # obexd quits without a transport
  assert 'radio.sh' in text and 'dpbridge-obex' in (HERE / 'radio.sh').read_text()


def run_bluez_debs(tmp_path, tar_bytes, sha, have_tar=None):
  text = (HERE / 'install_userspace.sh').read_text()
  fn = text[text.index('bluez_debs() {'):text.index('\n}\n', text.index('bluez_debs() {')) + 3]
  rel = tmp_path / 'rel'
  rel.mkdir(exist_ok=True)
  (rel / 'b.tar').write_bytes(tar_bytes)
  bin_ = tmp_path / 'bin'
  bin_.mkdir(exist_ok=True)
  (bin_ / 'curl').write_text(f'#!/bin/bash\necho curl >> {tmp_path}/curl.log\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n' +
                             f'cp {rel}/b.tar "$out"\n')
  (bin_ / 'curl').chmod(0o755)
  data = tmp_path / 'data'
  (data / 'debs').mkdir(parents=True, exist_ok=True)
  if have_tar is not None:
    (data / 'debs/b.tar').write_bytes(have_tar)
  lib = (HERE / 'lib.sh').read_text()
  script = f'set -euo pipefail\nSUDO=\n{lib}\nDEBS={data}/debs\nBZ=$DEBS/bluez-5.83\nBLUEZ_TAR=b.tar\nBLUEZ_SHA={sha}\nBLUEZ_URL=x\n{fn}\nbluez_debs\nls $BZ\n'
  import os
  r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=dict(os.environ, PATH=f'{bin_}:{os.environ["PATH"]}'))
  calls = (tmp_path / 'curl.log').read_text().count('curl') if (tmp_path / 'curl.log').exists() else 0
  return r, calls, None


def make_tar(tmp_path, damage=False):
  import hashlib
  import io
  import tarfile
  deb = b'!<arch>\nfake deb'
  sums = f'{hashlib.sha256(deb).hexdigest()}  bluez_5.83-0dpb1_arm64.deb\n'.encode()
  buf = io.BytesIO()
  with tarfile.open(fileobj=buf, mode='w') as t:
    for name, b in (('SHA256SUMS', sums), ('bluez_5.83-0dpb1_arm64.deb', deb + (b'x' if damage else b''))):
      ti = tarfile.TarInfo(name)
      ti.size = len(b)
      t.addfile(ti, io.BytesIO(b))
  b = buf.getvalue()
  return b, hashlib.sha256(b).hexdigest()


def test_bluez_debs_downloads_once_and_checks(tmp_path):
  tar, sha = make_tar(tmp_path)
  r, calls, _ = run_bluez_debs(tmp_path, tar, sha)
  assert r.returncode == 0, r.stderr
  assert 'bluez_5.83-0dpb1_arm64.deb' in r.stdout and calls == 1
  # tarball already on /data: no download (the AGNOS update case)
  r, calls, _ = run_bluez_debs(tmp_path, tar, sha)
  assert r.returncode == 0 and calls == 1


def test_bluez_debs_refuses_bad_download_and_damaged_debs(tmp_path):
  tar, sha = make_tar(tmp_path)
  (tmp_path / 'a').mkdir()
  r, _, _ = run_bluez_debs(tmp_path / 'a', tar, '0' * 64)
  assert r.returncode != 0 and 'does not match bluez.env' in r.stderr
  bad, bad_sha = make_tar(tmp_path, damage=True)
  (tmp_path / 'b').mkdir()
  r, _, _ = run_bluez_debs(tmp_path / 'b', bad, bad_sha)
  assert r.returncode != 0 and 'damaged' in r.stderr


def test_btfw_env_and_layout():
  env = env_file('firmware/btfw.env')
  assert re.fullmatch(r'[0-9a-f]{64}', env['BTFW_SHA']) and env['BTFW_URL'].endswith('/' + env['BTFW_TAR'])
  assert env['BTFW_URL'].startswith('https://github.com/Memberoffoxhound/TeslaPilot/releases/download/')
  assert 'BTIMG_URL' not in env  # comma's image is in our tarball, not fetched from comma
  pinned = {ln.split()[1] for ln in (HERE / 'firmware/firmware.sha256').read_text().splitlines()}
  made = re.search(r'^FILES="([^"]*)"', (HERE / 'firmware/make_btfw.sh').read_text(), re.M).group(1).split()
  assert set(made) == pinned
  text = script_text()
  for f in ('attach.sh', 'asound.conf', 'firmware/firmware.sha256', 'firmware/qca.sha256'):
    assert f in text
  assert 'deliver.sh push' not in text


def run_get_fw(tmp_path, files, tar_sha=None, have=None, pinned=None, curl=None):
  import hashlib
  import io
  import os
  import tarfile
  text = (HERE / 'install_userspace.sh').read_text()
  a = text.index('fw_ok() {')
  fns = text[a:text.index('\n}\n', text.index('get_fw() {')) + 3]
  here = tmp_path / 'here'
  (here / 'firmware').mkdir(parents=True, exist_ok=True)
  sums = ''.join(f'{hashlib.sha256(b).hexdigest()}  {n}\n' for n, b in (pinned or files).items())
  (here / 'firmware/firmware.sha256').write_text(sums)
  buf = io.BytesIO()
  with tarfile.open(fileobj=buf, mode='w') as t:
    for n, b in files.items():
      ti = tarfile.TarInfo(n)
      ti.size = len(b)
      t.addfile(ti, io.BytesIO(b))
  rel = tmp_path / 'rel'
  rel.mkdir(exist_ok=True)
  (rel / 'fw.tar').write_bytes(buf.getvalue())
  sha = tar_sha or hashlib.sha256(buf.getvalue()).hexdigest()
  bin_ = tmp_path / 'bin'
  bin_.mkdir(exist_ok=True)
  (bin_ / 'curl').write_text('#!/bin/bash\nfor a; do case $a in file://*) u=${a#file://} ;; esac; done\n' +
                             f'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\necho "curl $u" >> {tmp_path}/curl.log\ncp "$u" "$out"\n')
  if curl:
    (bin_ / 'curl').write_text(curl)
  (bin_ / 'curl').chmod(0o755)
  data = tmp_path / 'data'
  data.mkdir(exist_ok=True)
  for n, b in (have or {}).items():
    (data / n).write_bytes(b)
  lib = (HERE / 'lib.sh').read_text()
  script = (f'set -euo pipefail\nSUDO=\n{lib}\nDIR={data}\nHERE={here}\nBTFW_TAR=fw.tar\nBTFW_SHA={sha}\n' +
            f'BTFW_URL=file://{rel}/fw.tar\n{fns}\nfw_ok || get_fw\nfw_ok && echo FWOK\n')
  r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=dict(os.environ, PATH=f'{bin_}:{os.environ["PATH"]}'))
  log = (tmp_path / 'curl.log').read_text().splitlines() if (tmp_path / 'curl.log').exists() else []
  return r, log


FW = {'crbtfw21.tlv': b'tlv', 'crnv21.bin': b'nv', 'LICENSE.QualcommAtheros_ath10k': b'license', 'bluetooth.img': b'comma img'}


def test_get_fw_fresh_device(tmp_path):
  r, log = run_get_fw(tmp_path, FW)
  assert r.returncode == 0 and 'FWOK' in r.stdout, r.stderr
  assert len(log) == 1 and log[0].endswith('fw.tar')  # one download, bluetooth.img included
  assert (tmp_path / 'data/bluetooth.img').read_bytes() == b'comma img'
  # second run, as after an AGNOS update: everything is still on /data
  r, log = run_get_fw(tmp_path, FW)
  assert r.returncode == 0 and len(log) == 1


def test_get_fw_refuses_bad_downloads(tmp_path):
  (tmp_path / 'a').mkdir()
  r, _ = run_get_fw(tmp_path / 'a', FW, tar_sha='0' * 64)
  assert r.returncode != 0 and 'does not match btfw.env' in r.stderr
  (tmp_path / 'b').mkdir()
  r, _ = run_get_fw(tmp_path / 'b', {**FW, 'bluetooth.img': b'not comma'}, pinned=FW)
  assert r.returncode != 0 and 'does not match firmware.sha256' in r.stderr


def test_get_fw_no_network_is_a_temporary_failure(tmp_path):
  r, _ = run_get_fw(tmp_path, FW, curl='#!/bin/sh\nexit 6\n')  # could not resolve host
  assert r.returncode == 75 and 'download failed: firmware' in r.stderr
  text = (HERE / 'install_userspace.sh').read_text()
  assert text.count('dl_fail "') == 4  # btfw, BlueZ, apt-get update, apt-get download


def test_downloads_exit_75(tmp_path):
  import os
  lib = (HERE / 'lib.sh').read_text()
  r = subprocess.run(['bash', '-c', f'set -euo pipefail\n{lib}\nfalse || dl_fail "https://x"\necho no'], capture_output=True,
                     text=True, env=dict(os.environ))
  assert r.returncode == 75 and 'download failed: https://x' in r.stderr and 'no' not in r.stdout


def run_kernel_step(tmp_path, state, yes=1, reflash=0, flash_rc=0):
  import os
  text = (HERE / 'install_userspace.sh').read_text()
  fn = text[text.index('kernel_step() {'):text.index('\n}\n', text.index('kernel_step() {')) + 3]
  fake = tmp_path / 'kernel.sh'
  fake.write_text(f'echo "$*" >> {tmp_path}/k.log\n[ "$1" = status ] && echo state={state}\n[ "$1" = flash ] && exit {flash_rc}\nexit 0\n')
  lib = (HERE / 'lib.sh').read_text()
  script = (f'set -euo pipefail\nSUDO=\nYES={yes}\nREFLASH={reflash}\n{lib}\nKSH=(bash {fake})\n{fn}\n' +
            'if kernel_step; then echo REBOOT; else echo NOREBOOT; fi\n')
  r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=dict(os.environ))
  log = (tmp_path / 'k.log').read_text().splitlines()
  return r, log


def test_kernel_step_flashes_stock_and_reboots_last(tmp_path):
  r, log = run_kernel_step(tmp_path, 'offer')
  assert r.returncode == 0 and r.stdout.strip().endswith('REBOOT') and log == ['status', 'flash --yes']


def test_kernel_step_leaves_a_running_or_disabled_kernel_alone(tmp_path):
  for st, word in (('ok', 'running'), ('outdated', 'older dpbridge kernel'), ('off', 'disable'),
                   ('failed', 'last flash failed')):
    d = tmp_path / st
    d.mkdir()
    r, log = run_kernel_step(d, st)
    assert r.returncode == 0 and 'NOREBOOT' in r.stdout and word in r.stdout and log == ['status']


def test_kernel_step_skips_what_it_cannot_flash(tmp_path):
  # an AGNOS bump, another device or a full /data: print and go on, the install still succeeds and stamps
  for st in ('unsupported_agnos', 'unsupported_device', 'no_space'):
    d = tmp_path / st
    d.mkdir()
    r, log = run_kernel_step(d, st)
    assert r.returncode == 0 and 'NOREBOOT' in r.stdout and f'kernel: {st}, not flashed' in r.stdout and log == ['status']


def test_kernel_step_reflash_overrides_off_and_failed(tmp_path):
  for st in ('off', 'failed'):
    d = tmp_path / st
    d.mkdir()
    r, log = run_kernel_step(d, st, reflash=1)
    assert 'REBOOT' in r.stdout and log[-1] == 'flash --yes --retry'


def test_kernel_step_failure_stops_install_without_reboot(tmp_path):
  r, log = run_kernel_step(tmp_path, 'offer', flash_rc=1)
  assert r.returncode != 0 and 'kernel flash failed, see kernel.sh status' in r.stderr and 'nothing was switched' not in r.stderr and 'REBOOT' not in r.stdout


def test_kernel_step_passes_a_download_failure_on(tmp_path):
  r, log = run_kernel_step(tmp_path, 'offer', flash_rc=75)
  assert r.returncode == 75 and 'kernel flash failed' not in r.stderr and 'REBOOT' not in r.stdout


def test_kernel_step_dry_run_never_reboots(tmp_path):
  r, log = run_kernel_step(tmp_path, 'offer', yes=0)
  assert 'NOREBOOT' in r.stdout and log == ['status', 'flash']


def test_install_steps_and_reboot_is_last():
  text = script_text()
  steps = re.findall(r'echo "\[(\d)/4\]', text)
  assert steps == ['1', '2', '3', '4']
  tail = text[text.index('echo "[4/4] kernel"'):]
  assert tail.index('teardown') < tail.index('$SUDO "$REBOOT"')
  assert tail.index('progress rebooting 100') < tail.index('$SUDO "$REBOOT"')  # the last progress line
  assert 'post-boot' in text[:text.index('echo "[2/4]')]


def test_small_downloads_are_bounded(tmp_path):
  # btfw: the real curl call gets the stall flags and a 10 min cap per try
  logcurl = ('#!/bin/bash\necho "$*" > ' + f'{tmp_path}/args\n' +
             'for a; do case $a in file://*) u=${a#file://} ;; esac; done\n'
             'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\ncp "$u" "$out"\n')
  r, _ = run_get_fw(tmp_path, FW, curl=logcurl)
  assert r.returncode == 0, r.stderr
  args = (tmp_path / 'args').read_text().split()
  for flag, val in (('--max-time', '600'), ('--retry', '2'), ('--speed-limit', '1024'), ('--speed-time', '60'),
                    ('--connect-timeout', '20'), ('-C', '-')):
    assert args[args.index(flag) + 1] == val, flag
  text = (HERE / 'install_userspace.sh').read_text()
  assert text.count('$SUDO curl "${DL_OPTS[@]}" -o ') == 2  # btfw and BlueZ
  assert '$SUDO apt-get "${APT_OPTS[@]}" update' in text and '$SUDO apt-get "${APT_OPTS[@]}" download "$p"' in text
  assert not re.search(r'curl -fL|\$SUDO apt-get (update|download)', text)


def test_apt_has_a_timeout():
  lib = (HERE / 'lib.sh').read_text()
  r = subprocess.run(['bash', '-c', f'{lib}\necho "${{APT_OPTS[*]}}"'], capture_output=True, text=True)
  opts = r.stdout.split()
  assert {'Acquire::http::Timeout=20', 'Acquire::https::Timeout=20', 'Acquire::Retries=1'} <= set(opts)
  assert opts.count('-o') == 3
