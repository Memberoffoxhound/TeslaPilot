# Drives mac/deliver.sh with fake ssh/scp that run locally, against the fake partitions from test_flash_scripts.
import os
import subprocess
from pathlib import Path

from tools.dpbridge.tests.test_flash_scripts import dev  # noqa: F401  (fixture)

HERE = Path(__file__).resolve().parents[1]
FAKE_SSH = '''#!/bin/bash
# fake ssh: drop options, run the command locally with only what the "device" has, like a real login
while [ $# -gt 0 ]; do case $1 in -i|-o|-p) shift 2 ;; -*) shift ;; *) break ;; esac; done
shift
[ $# -eq 0 ] && exit 0
exec env -i PATH="$PATH" DPB_PARTS="$DPB_PARTS" SUDO="$SUDO" DPB_MODEL="$DPB_MODEL" DPB_VERSION="$DPB_VERSION" bash -c "$*"
'''
FAKE_SCP = '''#!/bin/bash
# fake scp: drop options and host: prefixes, then cp
a=()
while [ $# -gt 0 ]; do case $1 in -i|-o|-P) shift 2 ;; -*) shift ;; *) a+=("${1#*:}"); shift ;; esac; done
exec cp "${a[@]}"
'''


def deliver(env, *args):
  return subprocess.run(['bash', str(HERE / 'mac/deliver.sh'), '-i', env['KEYFILE'], *args], env=env, capture_output=True, text=True)


def setup_env(dev):
  tmp, parts, data, img, env = dev
  b = tmp / 'bin'
  (b / 'ssh').write_text(FAKE_SSH)
  (b / 'scp').write_text(FAKE_SCP)
  for f in ('ssh', 'scp'):
    (b / f).chmod(0o755)
  key = tmp / 'key'
  key.write_text('k')
  home = tmp / 'home'
  home.mkdir()
  remote = tmp / 'remote'
  return dict(env, KEYFILE=str(key), HOME=str(home), DPB_REMOTE=str(remote), BOOT=str(img)), remote, home


def test_push_flash_and_pull_backups(dev):
  tmp, parts, data, img, _ = dev
  env, remote, home = setup_env(dev)
  r = deliver(env, 'push')
  assert r.returncode == 0, r.stderr
  assert (remote / 'boot.img').read_bytes() == img.read_bytes()
  assert (remote / 'flash_boot.sh').exists() and (remote / 'dk_unpack.py').exists()

  before = (parts / 'boot_b').read_bytes()
  r = deliver(env, 'flash')
  assert r.returncode == 0 and 'dry run' in r.stdout and (parts / 'boot_b').read_bytes() == before

  r = deliver(env, 'flash', '--yes')
  assert r.returncode == 0, r.stderr
  assert (parts / 'boot_b').read_bytes().startswith(img.read_bytes())
  pulled = next((home / 'dpbridge-backup').iterdir())
  assert (pulled / 'boot_b.img').read_bytes() == before and (pulled / 'stock_slot').read_text().strip() == '_a'
  assert (remote / 'flash.log').exists() and (remote / 'flash.rc').read_text().strip() == '0'  # ran detached
  assert not (data / 'backup').exists()  # used the pushed copy in the remote dir, not a leaked DPB_DIR


def test_refuses_without_key_or_image(dev):
  env, remote, home = setup_env(dev)
  r = deliver(dict(env, KEYFILE='/nonexistent'), 'probe')
  assert r.returncode != 0 and 'no SSH key' in r.stderr
  r = deliver(dict(env, BOOT='/nonexistent/boot.img'), 'push')
  assert r.returncode != 0 and 'no boot.img' in r.stderr


def test_push_needs_a_matching_sha256(dev):
  tmp, parts, data, img, _ = dev
  env, remote, home = setup_env(dev)
  sha = Path(f'{img}.sha256')
  sha.write_text('0' * 64 + '  boot.img\n')
  r = deliver(env, 'push')
  assert r.returncode != 0 and 'does not match' in r.stderr and not (remote / 'boot.img').exists()
  sha.unlink()
  r = deliver(env, 'push')
  assert r.returncode != 0 and f'no {img}.sha256' in r.stderr


def test_failed_flash_is_reported_and_backups_not_pulled(dev):
  tmp, parts, data, img, _ = dev
  env, remote, home = setup_env(dev)
  assert deliver(env, 'push').returncode == 0
  (tmp / 'VERSION').write_text('20.7\n')
  r = deliver(env, 'flash', '--yes')
  assert r.returncode != 0 and 'flash failed' in r.stderr and 'built for AGNOS 20.6' in r.stdout
  assert not (home / 'dpbridge-backup').exists()


def test_unknown_command_prints_usage(dev):
  env, _, _ = setup_env(dev)
  r = deliver(env, 'frobnicate')
  assert r.returncode == 2 and 'backup-pull' in r.stdout


def stub_flash(remote, body):
  (remote / 'flash_boot.sh').write_text(f'#!/bin/bash\n{body}\n')


def test_flash_poll_stops_when_the_job_dies_without_a_result(dev):
  env, remote, home = setup_env(dev)
  assert deliver(env, 'push').returncode == 0
  stub_flash(remote, 'kill -9 $PPID')  # like a reboot: the wrapper never writes flash.rc
  r = deliver(dict(env, DPB_POLL_S='0.2', DPB_FLASH_MAX_S='5'), 'flash', '--yes')
  assert r.returncode != 0 and 'stopped without a result' in r.stderr
  assert not (remote / 'flash.rc').exists() and not (home / 'dpbridge-backup').exists()


def test_flash_poll_gives_up_after_the_cap(dev):
  env, remote, home = setup_env(dev)
  assert deliver(env, 'push').returncode == 0
  stub_flash(remote, 'sleep 20')
  try:
    r = deliver(dict(env, DPB_POLL_S='0.2', DPB_FLASH_MAX_S='2'), 'flash', '--yes')
    assert r.returncode != 0 and 'no result after' in r.stderr
  finally:
    subprocess.run(['pkill', '-f', str(remote / 'flash_boot.sh')])
