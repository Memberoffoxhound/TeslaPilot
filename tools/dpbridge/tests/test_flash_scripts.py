# Runs flash_boot.sh and restore_boot.sh against fake partitions (plain files) with a fake abctl.
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tools.dpbridge.tests.conftest import MB, MIRROR, write_sha

HERE = Path(__file__).resolve().parents[1]


def run(script, env, *args):
  return subprocess.run(['bash', str(HERE / script), *args], env=env, capture_output=True, text=True)


def snapshot(d):
  return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


def ops(tmp):
  log = tmp / 'ops.log'
  return log.read_text().splitlines() if log.exists() else []


def writes(tmp):
  # O_DIRECT reads are harmless; anything else is a write or an abctl call
  return [o for o in ops(tmp) if not o.startswith('direct ')]


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
  assert snapshot(parts) == before and not (data / 'backup').exists() and writes(tmp) == []


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
  assert snapshot(parts) == before and writes(tmp) == []


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


@pytest.mark.parametrize('slot', ['_a', '_b'])
def test_rotate_moves_stale_backup_and_flashes_other_slot(dev, slot):
  tmp, parts, data, img, env = dev
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  old_stock = (data / 'backup/boot_a.img').read_bytes()
  (tmp / 'slot').write_text(f'{slot}\n')
  (parts / f'boot{slot}').write_bytes(b'new agnos' + bytes(4 * MB - 9))
  running = (parts / f'boot{slot}').read_bytes()
  open(tmp / 'ops.log', 'w').close()
  r = run('flash_boot.sh', env, '--yes', '--rotate')
  assert r.returncode == 0, r.stderr
  oth = '_b' if slot == '_a' else '_a'
  assert (parts / f'boot{slot}').read_bytes() == running  # never the running slot
  assert (parts / f'boot{oth}').read_bytes().startswith(img.read_bytes())
  stale = [p for p in data.iterdir() if p.name.startswith('backup.stale-')]
  assert len(stale) == 1 and (stale[0] / 'boot_a.img').read_bytes() == old_stock
  assert (data / 'backup/stock_slot').read_text().strip() == slot
  assert not any(o.startswith('dd ') and o.endswith(f'/boot{slot}') for o in ops(tmp))


def test_rotate_still_refuses_from_dpbridge_slot(dev):
  tmp, parts, data, img, env = dev
  assert run('flash_boot.sh', env, '--yes').returncode == 0
  (tmp / 'slot').write_text('_b\n')
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes', '--rotate')
  assert r.returncode != 0 and 'running the dpbridge slot _b' in r.stderr and snapshot(parts) == before


def test_refuses_dpbridge_slot_even_without_backup(dev):
  tmp, parts, data, img, env = dev
  (parts / 'boot_a').write_bytes(img.read_bytes() + bytes(4 * MB - img.stat().st_size))
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes', '--rotate')
  assert r.returncode != 0 and 'running the dpbridge slot _a' in r.stderr and snapshot(parts) == before


# kernel.sh: the in-app flash helper
def kenv(dev, **kw):
  import hashlib
  tmp, parts, data, img, env = dev
  rel = tmp / 'release'
  rel.mkdir(exist_ok=True)
  (rel / 'boot.img').write_bytes(img.read_bytes())
  sha = hashlib.sha256(img.read_bytes()).hexdigest()
  (tmp / 'kernel.env').write_text(f'BOOT_SHA={sha}\nBOOT_SIZE={img.stat().st_size}\nBOOT_AGNOS=20.6\nBOOT_URL=file://{rel}/boot.img\n')
  curl = tmp / 'bin/curl'
  # fake curl: copies the file:// url to -o, logs the call
  curl.write_text(f"""#!/bin/bash
out=""; url=""
while [ $# -gt 0 ]; do case $1 in -o) out=$2; shift ;; file://*) url=${{1#file://}} ;; esac; shift; done
echo "curl $url" >> {tmp}/ops.log
[ -f "$url" ] || exit 22
cp "$url" "$out"
""")
  curl.chmod(0o755)
  reboot = tmp / 'bin/fake-reboot'
  reboot.write_text(f'#!/bin/sh\necho reboot >> {tmp}/ops.log\n')
  reboot.chmod(0o755)
  e = dict(env, DPB_KERNEL_ENV=str(tmp / 'kernel.env'), DPB_WCN=str(tmp / 'wcn3990'), DPB_REBOOT=str(reboot),
           DPB_CURL=str(curl), DPB_FREE_MB='10000', DPB_BOOT_ID=str(tmp / 'boot_id'))
  e.update(kw)
  (tmp / 'boot_id').write_text('boot-1\n')
  img.unlink()
  Path(f'{img}.sha256').unlink()
  return sha, e


def kv(out):
  return dict(ln.split('=', 1) for ln in out.splitlines() if '=' in ln)


def test_kernel_status_offers_on_stock(dev):
  sha, e = kenv(dev)
  r = run('kernel.sh', e, 'status')
  assert r.returncode == 0, r.stderr
  st = kv(r.stdout)
  assert st['state'] == 'offer' and st['sha'] == sha and st['agnos'] == '20.6'
  # only what is read: no slot, image or space keys (the 47 MB image is not hashed for status)
  assert not {'slot', 'target', 'image', 'free_mb', 'need_mb', 'last'} & set(st)


def run_on_dpbridge(tmp, parts, same=True):
  # the running slot a holds the pinned image (same) or an older dpbridge build
  img = (tmp / 'release/boot.img').read_bytes()
  boot = img if same else b'ANDROID!older' + img[13:]
  (parts / 'boot_a').write_bytes(boot + b'\0' * (4 * MB - len(boot)))
  (tmp / 'wcn3990').write_text('1')


@pytest.mark.parametrize('case, state', [('wcn', 'ok'), ('wcn_old', 'outdated'), ('agnos', 'unsupported_agnos'),
                                         ('model', 'unsupported_device'), ('space', 'no_space'), ('restored', 'offer'),
                                         ('disable', 'off'), ('pending', 'pending')])
def test_kernel_status_states(dev, case, state):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  if case in ('wcn', 'wcn_old'):
    run_on_dpbridge(tmp, parts, same=case == 'wcn')
  elif case == 'agnos':
    (tmp / 'VERSION').write_text('20.7\n')
  elif case == 'model':
    (tmp / 'model').write_bytes(b'comma tizi\0')
  elif case == 'space':
    e['DPB_FREE_MB'] = '10'
  elif case == 'restored':
    assert run('kernel.sh', e, 'flash', '--yes').returncode == 0
    assert run('restore_boot.sh', e, '--yes').returncode == 0
    (data / 'kernel/pending').unlink()
  elif case == 'disable':
    (data / 'disable').touch()
  elif case == 'pending':
    (data / 'kernel').mkdir()
    (data / 'kernel/pending').write_text(f'{sha} 20.6 _a _b\n')
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == state


def test_kernel_running_slot_is_hashed_once_per_boot(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  run_on_dpbridge(tmp, parts)
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'ok'
  assert (data / 'kernel/running').read_text() == 'boot-1 ok\n'
  # the cached answer is used for the rest of this boot
  (data / 'kernel/running').write_text('boot-1 outdated\n')
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'outdated'
  (tmp / 'boot_id').write_text('boot-2\n')
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'ok'


def test_kernel_flash_downloads_checks_and_never_reboots(dev):
  tmp, parts, data, img, env = dev
  boot_a = (parts / 'boot_a').read_bytes()
  sha, e = kenv(dev)
  r = run('kernel.sh', e, 'flash', '--yes')
  assert r.returncode == 0, r.stderr
  assert (parts / 'boot_a').read_bytes() == boot_a
  assert (parts / 'boot_b').read_bytes().startswith((tmp / 'release/boot.img').read_bytes())
  log = ops(tmp)
  assert 'reboot' not in log and log[-1] == 'abctl --set_active 1'  # the installer reboots, not kernel.sh
  assert (data / 'kernel/pending').read_text().split() == [sha, '20.6', '_a', '_b']


def test_kernel_flash_progress_lines(dev):
  sha, e = kenv(dev)
  r = run('kernel.sh', e, 'flash', '--yes')
  lines = [ln.split(': ', 1)[1] for ln in r.stdout.splitlines() if ln.startswith('  kernel: ')]
  pct = [int(ln.rsplit(' ', 1)[1].rstrip('%')) for ln in lines]
  steps = {ln.rsplit(' ', 1)[0] for ln in lines}
  assert pct == sorted(pct) and lines[-1] == 'switching slot 98%'
  assert {'downloading', 'verifying', 'backing up', 'writing slot b', 'reading back', 'switching slot'} <= steps
  # dry runs print no progress
  assert '  kernel: ' not in run('kernel.sh', e, 'flash').stdout


def test_kernel_flash_has_no_reboot_path():
  sh = (HERE / 'kernel.sh').read_text()
  assert 'REBOOT' not in sh and 'rebooting' not in sh and '--no-reboot' not in sh


def test_kernel_download_watcher_dies_with_the_script(dev):
  tmp = dev[0]
  sha, e = kenv(dev)
  # a curl that hangs; kernel.sh is killed hard mid-download
  (tmp / 'bin/curl').write_text('#!/bin/bash\nexec sleep 30\n')
  p = subprocess.Popen(['bash', str(HERE / 'kernel.sh'), 'flash', '--yes'], env=e, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)
  time.sleep(1.5)
  pids = subprocess.run(['pgrep', '-s', str(p.pid), '-f', 'kernel.sh'], capture_output=True, text=True).stdout.split()
  assert len(pids) >= 2  # kernel.sh and its watcher subshell
  os.kill(p.pid, signal.SIGKILL)
  p.wait()
  deadline = time.monotonic() + 5
  while time.monotonic() < deadline and subprocess.run(['pgrep', '-s', str(p.pid), '-f', 'kernel.sh']).returncode == 0:
    time.sleep(0.2)
  try:
    assert subprocess.run(['pgrep', '-s', str(p.pid), '-f', 'kernel.sh']).returncode != 0
  finally:
    subprocess.run(['pkill', '-9', '-s', str(p.pid)])  # the hung curl


def test_kernel_flash_from_b_writes_a(dev):
  tmp, parts, data, img, env = dev
  (tmp / 'slot').write_text('_b\n')
  boot_b = (parts / 'boot_b').read_bytes()
  sha, e = kenv(dev)
  r = run('kernel.sh', e, 'flash', '--yes')
  assert r.returncode == 0 and '  kernel: writing slot a 80%' in r.stdout
  assert (parts / 'boot_b').read_bytes() == boot_b
  assert (parts / 'boot_a').read_bytes().startswith((tmp / 'release/boot.img').read_bytes())
  assert 'abctl --set_active 0' in ops(tmp)


@pytest.mark.parametrize('case, msg', [('bad_download', 'does not match the pinned sha'),
                                       ('short_download', 'wrong size'),
                                       ('agnos', 'AGNOS 20.7 but the image is for 20.6'),
                                       ('model', 'not a comma 4 (mici)'),
                                       ('running_dpbridge', 'a dpbridge kernel is already running'),
                                       ('space', 'not enough space'), ('no_release', 'download failed'),
                                       ('disable', 'kernel flash is off')])
def test_kernel_flash_refuses(dev, case, msg):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  if case == 'model':
    (tmp / 'model').write_bytes(b'comma tizi\0')
  elif case == 'bad_download':
    b = (tmp / 'release/boot.img').read_bytes()
    (tmp / 'release/boot.img').write_bytes(b[:-1] + b'x')
  elif case == 'short_download':
    (tmp / 'release/boot.img').write_bytes(b'ANDROID!' + bytes(10))
  elif case == 'agnos':
    (tmp / 'VERSION').write_text('20.7\n')
  elif case == 'running_dpbridge':
    (tmp / 'wcn3990').write_text('1')
  elif case == 'space':
    e['DPB_FREE_MB'] = '10'
  elif case == 'no_release':
    (tmp / 'release/boot.img').unlink()
  elif case == 'disable':
    (data / 'disable').touch()
  before = snapshot(parts)
  r = run('kernel.sh', e, 'flash', '--yes')
  assert r.returncode != 0 and 'refusing' in r.stderr and msg in r.stderr, r.stderr
  assert snapshot(parts) == before
  assert not [o for o in ops(tmp) if o.startswith(('dd ', 'abctl', 'reboot'))]
  assert not (data / 'boot.img').exists() or case not in ('bad_download', 'short_download')


def test_kernel_retry_overrides_disable(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  (data / 'disable').touch()
  assert run('kernel.sh', e, 'flash', '--yes', '--retry').returncode == 0 and ops(tmp)[-1] == 'abctl --set_active 1'
  assert (data / 'disable').exists()  # the radio's switch, left alone


def test_kernel_reflash_after_agnos_update_rotates(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  assert run('kernel.sh', e, 'flash', '--yes').returncode == 0
  # AGNOS update: now running stock on b, slot a has the old dpbridge kernel
  (tmp / 'slot').write_text('_b\n')
  (parts / 'boot_b').write_bytes(b'new agnos' + bytes(4 * MB - 9))
  assert run('kernel.sh', e, 'post-boot', '--yes').returncode == 0  # the installer's first step
  (data / 'kernel/failed').unlink()  # the update, not a failed boot, moved the slot
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'offer'
  open(tmp / 'ops.log', 'w').close()
  r = run('kernel.sh', e, 'flash', '--yes')
  assert r.returncode == 0, r.stderr
  assert (parts / 'boot_b').read_bytes().startswith(b'new agnos')
  assert any(p.name.startswith('backup.stale-') for p in data.iterdir())
  assert 'curl' not in ' '.join(ops(tmp))  # image already on /data


def test_kernel_prunes_old_backups(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev, DPB_KEEP_BACKUPS='2')
  for i in range(4):
    d = data / f'backup.2026010{i}-000000'
    d.mkdir()
    os.utime(d, (1000 + i, 1000 + i))
  assert run('kernel.sh', e, 'flash', '--yes').returncode == 0
  old = sorted(p.name for p in data.iterdir() if p.name.startswith('backup.'))
  assert len(old) == 2 and (data / 'backup/stock_slot').exists()


@pytest.mark.parametrize('booted', [True, False])
def test_kernel_post_boot(dev, booted):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  (data / 'kernel').mkdir()
  (data / 'kernel/pending').write_text(f'{sha} 20.6 _a _b\n')
  if booted:
    run_on_dpbridge(tmp, parts)
  # dry run: records nothing
  r = run('kernel.sh', e, 'post-boot')
  assert r.returncode == 0 and (data / 'kernel/pending').exists()
  assert run('kernel.sh', e, 'post-boot', '--yes').returncode == 0
  assert not (data / 'kernel/pending').exists()
  if booted:
    assert (data / 'kernel/ok').exists() and kv(run('kernel.sh', e, 'status').stdout)['state'] == 'ok'
  else:
    assert (data / 'kernel/failed').exists()
    st = kv(run('kernel.sh', e, 'status').stdout)
    assert st['state'] == 'failed'
    # no loop: the same image, AGNOS and slot is not flashed again without --retry
    before = snapshot(parts)
    r = run('kernel.sh', e, 'flash', '--yes')
    assert r.returncode != 0 and '--reflash' in r.stderr and snapshot(parts) == before
    # an AGNOS update moves the running slot, so it is offered again
    (tmp / 'slot').write_text('_b\n')
    assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'offer'


def test_kernel_env_matches_flash_script():
  env = dict(ln.split('=', 1) for ln in (HERE / 'firmware/kernel.env').read_text().splitlines() if '=' in ln and not ln.startswith('#'))
  agnos = next(ln for ln in (HERE / 'flash_boot.sh').read_text().splitlines() if ln.startswith('AGNOS='))
  assert agnos == f"AGNOS={env['BOOT_AGNOS']}" and env['BOOT_SIZE'] == '47454208' and len(env['BOOT_SHA']) == 64
  assert env['BOOT_URL'].startswith('https://github.com/Memberoffoxhound/TeslaPilot/releases/download/')


def test_kernel_failed_flash_is_not_repeated(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  r = run('kernel.sh', dict(e, CORRUPT='boot_b'), 'flash', '--yes')
  assert r.returncode != 0 and 'readback mismatch' in r.stderr and 'reboot' not in ops(tmp)
  assert (data / 'kernel/failed').read_text().split() == [sha, '20.6', '_a']
  assert not (data / 'kernel/pending').exists()
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'failed'
  assert run('kernel.sh', e, 'flash', '--yes', '--retry').returncode == 0 and ops(tmp)[-1] == 'abctl --set_active 1'


def test_kernel_pending_is_written_before_any_write(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  # power lost right after the slot switch: pending is already there for post-boot
  e['PATH'] = f"{tmp / 'cut'}:{e['PATH']}"
  (tmp / 'cut').mkdir()
  (tmp / 'cut/abctl').write_text(f'#!/bin/sh\ncase $1 in --set_active) kill -9 0 ;; esac\nexec {tmp}/bin/abctl "$@"\n')
  (tmp / 'cut/abctl').chmod(0o755)
  # own session, so the kill takes kernel.sh and flash_boot.sh down at once and nothing else
  subprocess.run(['bash', str(HERE / 'kernel.sh'), 'flash', '--yes'], env=e, capture_output=True, start_new_session=True)
  assert (data / 'kernel/pending').read_text().split() == [sha, '20.6', '_a', '_b']
  assert run('kernel.sh', e, 'post-boot', '--yes').returncode == 0
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'failed'


def test_kernel_dry_run_does_not_download(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  r = run('kernel.sh', e, 'flash')
  assert r.returncode == 0 and 'stops before the download' in r.stdout
  assert 'curl' not in ' '.join(ops(tmp)) and not (data / 'boot.img').exists()


def test_restore_then_install_flashes_again(dev):
  tmp, parts, data, img, env = dev
  sha, e = kenv(dev)
  assert run('kernel.sh', e, 'flash', '--yes').returncode == 0
  # booted dpbridge on b, then restored to stock a and rebooted
  (tmp / 'wcn3990').write_text('1')
  assert run('kernel.sh', e, 'post-boot', '--yes').returncode == 0 and (data / 'kernel/ok').exists()
  assert run('restore_boot.sh', e, '--yes').returncode == 0
  (tmp / 'wcn3990').unlink()
  assert 'abctl --set_active 0' in ops(tmp)
  assert kv(run('kernel.sh', e, 'status').stdout)['state'] == 'offer'  # the next install flashes b again
  open(tmp / 'ops.log', 'w').close()
  assert run('kernel.sh', e, 'flash', '--yes').returncode == 0 and 'abctl --set_active 1' in ops(tmp)


def test_rotate_refuses_on_a_dpbridge_kernel(dev):
  tmp, parts, data, img, env = dev
  (tmp / 'wcn3990').write_text('1')
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes', '--rotate')
  assert r.returncode != 0 and 'a dpbridge kernel is running' in r.stderr and snapshot(parts) == before


def test_flash_needs_block_devices_up_front(dev):
  tmp, parts, data, img, env = dev
  (parts / 'devcfg_b').unlink()
  before = snapshot(parts)
  r = run('flash_boot.sh', env, '--yes')
  assert r.returncode != 0 and 'devcfg_b is not a block device' in r.stderr
  assert snapshot(parts) == before and not [o for o in ops(tmp) if o.startswith('abctl')]
