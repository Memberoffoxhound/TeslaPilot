# Runs flash_boot.sh and restore_boot.sh against fake partitions (plain files) with a fake abctl.
import os
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
MB = 1 << 20


@pytest.fixture
def dev(tmp_path):
  parts, data, bin_ = tmp_path / 'parts', tmp_path / 'data', tmp_path / 'bin'
  for d in (parts, data, bin_):
    d.mkdir()
  for name, size in (('boot', 4 * MB), ('system', 2 * MB), ('modem', MB)):
    (parts / f'{name}_a').write_bytes(name.encode() + b'A' * (size - len(name)))
    (parts / f'{name}_b').write_bytes(b'old' + b'B' * (size - 3))
  (parts / 'userdata').write_bytes(b'u' * MB)
  (bin_ / 'abctl').write_text(f'#!/bin/sh\n[ "$1" = --boot_slot ] && cat {tmp_path}/slot && exit 0\necho "$@" >> {tmp_path}/abctl.log\n')
  (bin_ / 'blockdev').write_text('#!/bin/sh\nstat -c %s "$2"\n')
  for f in bin_.iterdir():
    f.chmod(0o755)
  (tmp_path / 'slot').write_text('_a\n')
  img = data / 'boot.img'
  img.write_bytes(b'ANDROID!' + os.urandom(MB))
  env = dict(os.environ, PATH=f'{bin_}:{os.environ["PATH"]}', DPB_DIR=str(data), DPB_PARTS=str(parts), SUDO='')
  return tmp_path, parts, data, img, env


def run(script, env, *args):
  return subprocess.run(['bash', str(HERE / script), *args], env=env, capture_output=True, text=True)


def snapshot(d):
  return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


def test_dry_run_changes_nothing(dev):
  tmp, parts, data, img, env = dev
  before = snapshot(parts)
  r = run('flash_boot.sh', env)
  assert r.returncode == 0, r.stderr
  assert 'dry run' in r.stdout and 'boot_b' in r.stdout
  assert snapshot(parts) == before and not (data / 'backup').exists() and not (tmp / 'abctl.log').exists()


def test_flash_writes_other_slot_only(dev):
  tmp, parts, data, img, env = dev
  boot_a, boot_b = (parts / 'boot_a').read_bytes(), (parts / 'boot_b').read_bytes()
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode == 0, r.stderr
  assert (parts / 'boot_a').read_bytes() == boot_a
  assert (parts / 'boot_b').read_bytes().startswith(img.read_bytes())
  assert (parts / 'system_b').read_bytes() == (parts / 'system_a').read_bytes()
  assert (parts / 'modem_b').read_bytes() == (parts / 'modem_a').read_bytes()
  assert (data / 'backup/boot_a.img').read_bytes() == boot_a
  assert (data / 'backup/boot_b.img').read_bytes() == boot_b
  assert (data / 'backup/stock_slot').read_text().strip() == '_a'
  assert (tmp / 'abctl.log').read_text().split() == ['--set_active', '1']


def test_flash_from_slot_b_targets_a(dev):
  tmp, parts, data, img, env = dev
  (tmp / 'slot').write_text('_b\n')
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  assert (parts / 'boot_a').read_bytes().startswith(img.read_bytes())
  assert (tmp / 'abctl.log').read_text().split() == ['--set_active', '0']


@pytest.mark.parametrize('breakage', ['no_image', 'bad_slot', 'too_big', 'not_android', 'bad_sha', 'size_mismatch'])
def test_flash_refuses(dev, breakage):
  tmp, parts, data, img, env = dev
  if breakage == 'no_image':
    img.unlink()
  elif breakage == 'bad_slot':
    (tmp / 'slot').write_text('\n')
  elif breakage == 'too_big':
    img.write_bytes(b'ANDROID!' + bytes(5 * MB))
  elif breakage == 'not_android':
    img.write_bytes(bytes(MB))
  elif breakage == 'bad_sha':
    (data / 'boot.img.sha256').write_text('0' * 64 + '  boot.img\n')
  elif breakage == 'size_mismatch':
    (parts / 'modem_b').write_bytes(b'x')
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode != 0 and 'refusing' in r.stderr
  assert snapshot(parts) == before and not (tmp / 'abctl.log').exists()


def test_restore_goes_back_to_stock(dev):
  tmp, parts, data, img, env = dev
  boot_b = (parts / 'boot_b').read_bytes()
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  r = run('restore_boot.sh', env, '--yes', '--write')
  assert r.returncode == 0, r.stderr
  assert (parts / 'boot_b').read_bytes() == boot_b
  assert (tmp / 'abctl.log').read_text().split()[-2:] == ['--set_active', '0']


def test_restore_refuses_damaged_backup(dev):
  tmp, parts, data, img, env = dev
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  (data / 'backup/boot_b.img').write_bytes(b'junk')
  r = run('restore_boot.sh', env, '--yes', '--write')
  assert r.returncode != 0 and 'damaged' in r.stderr


def test_install_refuses_on_stock_kernel(dev):
  if os.path.exists('/sys/module/hci_uart/parameters/wcn3990'):
    pytest.skip('host has the dpbridge kernel')
  r = run('install_userspace.sh', dev[4], '--yes')
  assert r.returncode != 0 and 'flash the dpbridge boot.img' in r.stderr


def test_dk_unpack_reads_only_dashkit_messages():
  import importlib.util
  from types import SimpleNamespace
  from openpilot.system.dpbridge.dkwire import pack
  spec = importlib.util.spec_from_file_location('dk_unpack', HERE / 'dk_unpack.py')
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  dk = SimpleNamespace(which=lambda: 'customReservedRawData0', logMonoTime=5,
                       customReservedRawData0=pack([(1, 0, 0x257, b'\x01'), (2, 1, 0x249, b'')]))
  other = SimpleNamespace(which=lambda: 'carState', logMonoTime=6)
  bad = SimpleNamespace(which=lambda: 'customReservedRawData0', logMonoTime=7, customReservedRawData0=b'\x09')
  rows = list(mod.unpack([dk, other, bad]))
  assert [(r[2], r[3]) for r in rows] == [(0, 0x257), (1, 0x249)] and rows[0][4] == b'\x01'


def test_reflash_keeps_old_backup_and_refuses_from_dpbridge_slot(dev):
  tmp, parts, data, img, env = dev
  orig_b = (parts / 'boot_b').read_bytes()
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  assert run('flash_boot.sh', env, '--yes').returncode == 0  # again from stock slot a
  old = [p for p in data.iterdir() if p.name.startswith('backup.')]
  assert len(old) == 1 and (old[0] / 'boot_b.img').read_bytes() == orig_b
  (tmp / 'slot').write_text('_b\n')  # now booted into the dpbridge slot
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode != 0 and 'overwrite stock _a' in r.stderr and snapshot(parts) == before
