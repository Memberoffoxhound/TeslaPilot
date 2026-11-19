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
  import hashlib
  text = (HERE / 'install_userspace.sh').read_text()
  fn = text[text.index('bluez_debs() {'):text.index('\n}\n', text.index('bluez_debs() {')) + 3]
  rel = tmp_path / 'rel'
  rel.mkdir(exist_ok=True)
  (rel / 'b.tar').write_bytes(tar_bytes)
  bin_ = tmp_path / 'bin'
  bin_.mkdir(exist_ok=True)
  (bin_ / 'curl').write_text(f'#!/bin/bash\necho curl >> {tmp_path}/curl.log\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
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
  # comma's image is fetched from comma's repo at the pinned commit, never re-hosted
  assert env['BTIMG_URL'].startswith('https://media.githubusercontent.com/media/commaai/agnos-builder/140ed0c')
  pinned = {ln.split()[1] for ln in (HERE / 'firmware/firmware.sha256').read_text().splitlines()}
  made = re.search(r'^FILES="([^"]*)"', (HERE / 'firmware/make_btfw.sh').read_text(), re.M).group(1).split()
  assert set(made) | {'bluetooth.img'} == pinned
  text = script_text()
  for f in ('attach.sh', 'asound.conf', 'firmware/firmware.sha256', 'firmware/qca.sha256'):
    assert f in text
  assert 'deliver.sh push' not in text


def run_get_fw(tmp_path, files, tar_sha=None, have=None, img=None):
  import hashlib
  import io
  import os
  import tarfile
  text = (HERE / 'install_userspace.sh').read_text()
  a = text.index('fw_ok() {')
  fns = text[a:text.index('\n}\n', text.index('get_fw() {')) + 3]
  here = tmp_path / 'here'
  (here / 'firmware').mkdir(parents=True, exist_ok=True)
  img = img if img is not None else b'comma img'
  sums = ''.join(f'{hashlib.sha256(b).hexdigest()}  {n}\n' for n, b in {**files, 'bluetooth.img': b'comma img'}.items())
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
  (rel / 'bluetooth.img').write_bytes(img)
  sha = tar_sha or hashlib.sha256(buf.getvalue()).hexdigest()
  bin_ = tmp_path / 'bin'
  bin_.mkdir(exist_ok=True)
  (bin_ / 'curl').write_text(f'#!/bin/bash\nfor a; do case $a in file://*) u=${{a#file://}} ;; esac; done\n'
                             f'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\necho "curl $u" >> {tmp_path}/curl.log\ncp "$u" "$out"\n')
  (bin_ / 'curl').chmod(0o755)
  data = tmp_path / 'data'
  data.mkdir(exist_ok=True)
  for n, b in (have or {}).items():
    (data / n).write_bytes(b)
  lib = (HERE / 'lib.sh').read_text()
  script = (f'set -euo pipefail\nSUDO=\n{lib}\nDIR={data}\nHERE={here}\nBTFW_TAR=fw.tar\nBTFW_SHA={sha}\n'
            f'BTFW_URL=file://{rel}/fw.tar\nBTIMG_URL=file://{rel}/bluetooth.img\n{fns}\nfw_ok || get_fw\nfw_ok && echo FWOK\n')
  r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=dict(os.environ, PATH=f'{bin_}:{os.environ["PATH"]}'))
  log = (tmp_path / 'curl.log').read_text().splitlines() if (tmp_path / 'curl.log').exists() else []
  return r, log


FW = {'crbtfw21.tlv': b'tlv', 'crnv21.bin': b'nv', 'LICENSE.QualcommAtheros_ath10k': b'license'}


def test_get_fw_fresh_device(tmp_path):
  r, log = run_get_fw(tmp_path, FW)
  assert r.returncode == 0 and 'FWOK' in r.stdout, r.stderr
  assert len(log) == 2 and log[0].endswith('fw.tar') and log[1].endswith('bluetooth.img')
  # second run, as after an AGNOS update: everything is still on /data
  r, log = run_get_fw(tmp_path, FW)
  assert r.returncode == 0 and len(log) == 2


def test_get_fw_refuses_bad_downloads(tmp_path):
  (tmp_path / 'a').mkdir()
  r, _ = run_get_fw(tmp_path / 'a', FW, tar_sha='0' * 64)
  assert r.returncode != 0 and 'does not match btfw.env' in r.stderr
  (tmp_path / 'b').mkdir()
  r, _ = run_get_fw(tmp_path / 'b', FW, img=b'not comma')
  assert r.returncode != 0 and 'does not match firmware.sha256' in r.stderr
