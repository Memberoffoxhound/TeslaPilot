# Runs flash_boot.sh and restore_boot.sh against fake partitions (plain files) with a fake abctl.
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
MB = 1 << 20


REAL_DD = shutil.which('dd')
MIRROR = ('xbl', 'xbl_config', 'abl', 'aop', 'devcfg', 'system')


@pytest.fixture
def dev(tmp_path):
  parts, data, bin_ = tmp_path / 'parts', tmp_path / 'data', tmp_path / 'bin'
  for d in (parts, data, bin_):
    d.mkdir()
  for name, size in (('boot', 4 * MB), *((n, MB) for n in MIRROR), ('modem', MB)):
    (parts / f'{name}_a').write_bytes(name.encode() + b'A' * (size - len(name)))
    (parts / f'{name}_b').write_bytes(b'old' + b'B' * (size - 3))
  (parts / 'userdata').write_bytes(b'u' * MB)
  log = tmp_path / 'ops.log'
  (bin_ / 'abctl').write_text(f'#!/bin/sh\n[ "$1" = --boot_slot ] && cat {tmp_path}/slot && exit 0\necho abctl "$@" >> {log}\n'
                              f'[ -f {tmp_path}/abctl_broken ] && echo "abctl: missing partition xbl_b" && exit 0\n'
                              'echo "setting /dev/disk/by-partlabel/xbl_x lun as boot lun"\n')
  (bin_ / 'blockdev').write_text('#!/bin/sh\nstat -c %s "$2"\n')
  # logs every write; flips the first byte of a target matching $CORRUPT after writing it
  (bin_ / 'dd').write_text(f"""#!/bin/bash
{REAL_DD} "$@" || exit
for a; do
  case $a in
    of=*) echo "dd ${{a#of=}}" >> {log}
          [ -n "$CORRUPT" ] && [[ $a == *$CORRUPT ]] && printf X | {REAL_DD} "$a" conv=notrunc status=none ;;
    if=*) [[ " $* " == *" iflag=direct "* ]] && echo "direct ${{a#if=}}" >> {log} ;;
  esac
done
exit 0
""")
  for f in bin_.iterdir():
    f.chmod(0o755)
  (tmp_path / 'slot').write_text('_a\n')
  (tmp_path / 'model').write_bytes(b'comma mici\0')
  (tmp_path / 'VERSION').write_text('20.6\n')
  img = data / 'boot.img'
  img.write_bytes(b'ANDROID!' + os.urandom(MB))
  write_sha(img)
  env = dict(os.environ, PATH=f'{bin_}:{os.environ["PATH"]}', DPB_DIR=str(data), DPB_PARTS=str(parts), SUDO='',
             DPB_MODEL=str(tmp_path / 'model'), DPB_VERSION=str(tmp_path / 'VERSION'))
  return tmp_path, parts, data, img, env


def write_sha(img):
  Path(f'{img}.sha256').write_text(f'{hashlib.sha256(img.read_bytes()).hexdigest()}  boot.img\n')


def run(script, env, *args):
  return subprocess.run(['bash', str(HERE / script), *args], env=env, capture_output=True, text=True)


def snapshot(d):
  return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


def ops(tmp):
  log = tmp / 'ops.log'
  return log.read_text().splitlines() if log.exists() else []


def test_mirror_list_is_agnos_json_minus_boot():
  line = next(ln for ln in (HERE / 'flash_boot.sh').read_text().splitlines() if ln.startswith('MIRROR='))
  agnos = json.loads((HERE.parents[1] / 'openpilot/common/hardware/comma/agnos.json').read_text())
  assert line.split('"')[1].split() == [p['name'] for p in agnos if p['has_ab'] and p['name'] != 'boot']
  assert tuple(line.split('"')[1].split()) == MIRROR


def test_dry_run_changes_nothing(dev):
  tmp, parts, data, img, env = dev
  before = snapshot(parts)
  r = run('flash_boot.sh', env)
  assert r.returncode == 0, r.stderr
  assert 'dry run' in r.stdout and 'boot_b' in r.stdout
  assert snapshot(parts) == before and not (data / 'backup').exists() and ops(tmp) == []


def test_flash_writes_other_slot_only(dev):
  tmp, parts, data, img, env = dev
  boot_a, boot_b, modem_b = (parts / 'boot_a').read_bytes(), (parts / 'boot_b').read_bytes(), (parts / 'modem_b').read_bytes()
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode == 0, r.stderr
  assert (parts / 'boot_a').read_bytes() == boot_a
  assert (parts / 'boot_b').read_bytes().startswith(img.read_bytes())
  for n in MIRROR:
    assert (parts / f'{n}_b').read_bytes() == (parts / f'{n}_a').read_bytes()
  assert (parts / 'modem_b').read_bytes() == modem_b  # not in agnos.json, left alone
  assert (data / 'backup/boot_a.img').read_bytes() == boot_a
  assert (data / 'backup/boot_b.img').read_bytes() == boot_b
  assert (data / 'backup/stock_slot').read_text().strip() == '_a'
  assert [o for o in ops(tmp) if o.startswith('abctl')] == ['abctl --set_unbootable 1', 'abctl --set_active 1']


def test_slot_b_is_unbootable_before_any_write_to_it(dev):
  tmp, parts, data, img, env = dev
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  log = ops(tmp)
  first_write = next(i for i, o in enumerate(log) if o.startswith('dd ') and o.endswith('_b'))
  assert log.index('abctl --set_unbootable 1') < first_write
  assert log[-1] == 'abctl --set_active 1'
  # readbacks bypass the page cache
  assert f'direct {parts}/boot_b' in log and f'direct {parts}/system_b' in log


def test_flash_skips_partitions_that_already_match(dev):
  tmp, parts, data, img, env = dev
  (parts / 'xbl_b').write_bytes((parts / 'xbl_a').read_bytes())
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode == 0 and 'xbl already matches' in r.stdout
  writes = [o for o in ops(tmp) if o.startswith('dd ')]
  assert not any(o.endswith('/xbl_b') for o in writes) and any(o.endswith('/xbl_config_b') for o in writes)


def test_flash_from_slot_b_targets_a(dev):
  tmp, parts, data, img, env = dev
  (tmp / 'slot').write_text('_b\n')
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  assert (parts / 'boot_a').read_bytes().startswith(img.read_bytes())
  assert [o for o in ops(tmp) if o.startswith('abctl')] == ['abctl --set_unbootable 0', 'abctl --set_active 0']


@pytest.mark.parametrize('breakage', ['no_image', 'no_sha', 'bad_slot', 'too_big', 'not_android', 'bad_sha',
                                      'size_mismatch', 'not_mici', 'other_agnos'])
def test_flash_refuses(dev, breakage):
  tmp, parts, data, img, env = dev
  if breakage == 'no_image':
    img.unlink()
  elif breakage == 'no_sha':
    Path(f'{img}.sha256').unlink()
  elif breakage == 'bad_slot':
    (tmp / 'slot').write_text('\n')
  elif breakage == 'too_big':
    img.write_bytes(b'ANDROID!' + bytes(5 * MB))
    write_sha(img)
  elif breakage == 'not_android':
    img.write_bytes(bytes(MB))
    write_sha(img)
  elif breakage == 'bad_sha':
    Path(f'{img}.sha256').write_text('0' * 64 + '  boot.img\n')
  elif breakage == 'size_mismatch':
    (parts / 'system_b').write_bytes(b'x')
  elif breakage == 'not_mici':
    (tmp / 'model').write_bytes(b'comma tizi\0')
  elif breakage == 'other_agnos':
    (tmp / 'VERSION').write_text('20.7\n')
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode != 0 and 'refusing' in r.stderr
  assert snapshot(parts) == before and ops(tmp) == []


@pytest.mark.parametrize('target, msg', [('boot_b', 'boot_b readback mismatch'), ('system_b', 'system_b readback mismatch'),
                                         ('xbl_b', 'xbl_b readback mismatch'), ('backup/boot_b.img', 'backup of boot_b does not match')])
def test_flash_catches_bad_writes(dev, target, msg):
  tmp, parts, data, img, env = dev
  r = run('flash_boot.sh', dict(env, CORRUPT=target), '--yes')
  assert r.returncode != 0 and msg in r.stderr
  assert 'abctl --set_active 1' not in ops(tmp)


def test_restore_goes_back_to_stock(dev):
  tmp, parts, data, img, env = dev
  boot_a = (parts / 'boot_a').read_bytes()
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  r = run('restore_boot.sh', env, '--yes', '--write')
  assert r.returncode == 0, r.stderr
  assert (parts / 'boot_b').read_bytes() == boot_a  # the stock kernel, matching the mirrored system
  assert ops(tmp)[-1] == 'abctl --set_active 0'


def test_restore_catches_bad_write(dev):
  tmp, parts, data, img, env = dev
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  r = run('restore_boot.sh', dict(env, CORRUPT='boot_b'), '--yes', '--write')
  assert r.returncode != 0 and 'readback mismatch' in r.stderr
  assert ops(tmp)[-1] != 'abctl --set_active 0'


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
  assert r.returncode != 0 and 'running the dpbridge slot _b' in r.stderr and snapshot(parts) == before


@pytest.mark.parametrize('slot', ['_a', '_b'])
def test_flash_refuses_after_agnos_update(dev, slot):
  tmp, parts, data, img, env = dev
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  (tmp / 'slot').write_text(f'{slot}\n')
  (parts / f'boot{slot}').write_bytes(b'new agnos' + bytes(4 * MB - 9))
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode != 0 and 'AGNOS update?' in r.stderr and snapshot(parts) == before


def test_flash_catches_abctl_failure(dev):
  # abctl --set_active exits 0 on failure, the script must read its output
  tmp, parts, data, img, env = dev
  (tmp / 'abctl_broken').touch()
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode != 0 and 'set_active 1 failed' in r.stderr
