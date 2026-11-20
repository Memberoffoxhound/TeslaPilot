# boot.py: the first-boot run of the installer before manager.
import hashlib
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


class FakePage:
  # the kernel page: answers ask() with `answer`, records what it was shown
  def __init__(self, answer='accept'):
    self.answer, self.asked, self.seen, self.names, self.notes, self.waits, self.closed = answer, 0, [], [], [], [], False

  def ask(self):
    self.asked += 1
    return self.answer

  def progress(self, pct, name):
    self.seen.append(pct)
    self.names.append(name)

  def connecting(self, secs):
    self.waits.append(secs)

  def note(self, head, text):
    self.notes.append((head, text))

  def close(self):
    self.closed = True


def load(tmp_path, monkeypatch, install='echo "[1/4] x"; exit 0', state='ok', model='comma mici', slot='_a'):
  for k, v in (('DPB_DIR', tmp_path / 'data'), ('DPB_BOOT_DIR', tmp_path / 'data'), ('DPB_MODEL', tmp_path / 'model'), ('DPB_VERSION', tmp_path / 'VERSION'),
               ('DPB_BOOT_TIMEOUT_S', '5'), ('DPB_NOTE_S', '0'), ('DPB_NET_WAIT_S', '0'),
               ('DPB_BT_PARAM', tmp_path / 'DpbBluetooth')):  # unused now, kept so a migration would show
    monkeypatch.setenv(k, str(v))
  (tmp_path / 'data').mkdir(exist_ok=True)
  (tmp_path / 'model').write_text(model)
  (tmp_path / 'VERSION').write_text('20.6')
  spec = importlib.util.spec_from_file_location('dpb_boot', HERE / 'boot.py')
  m = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(m)
  (tmp_path / 'install.sh').write_text(f'echo "$*" >> {tmp_path}/runs\n{install}\n')
  (tmp_path / 'kernel.sh').write_text(f'echo state={state}\n')
  (tmp_path / 'reboot').write_text(f'echo reboot >> {tmp_path}/reboots\n')
  m.INSTALL, m.KERNEL, m.SUDO = str(tmp_path / 'install.sh'), str(tmp_path / 'kernel.sh'), []
  m.REBOOT = ['bash', str(tmp_path / 'reboot')]
  m.slot = lambda: slot
  m.online = lambda: True  # no network in tests
  return m


def runs(tmp_path):
  p = tmp_path / 'runs'
  return p.read_text().splitlines() if p.exists() else []


def pin_cache(m, tmp_path, btfw=b'fw', bluez=b'bz', boot=b'boot', write=True):
  (tmp_path / 'data/debs').mkdir(exist_ok=True)
  if write:
    (tmp_path / 'data/debs/fw.tar').write_bytes(btfw)
    (tmp_path / 'data/debs/bz.tar').write_bytes(bluez)
    (tmp_path / 'data/boot.img').write_bytes(boot)
  pins = {
    ('firmware/btfw.env', 'BTFW_TAR'): 'fw.tar',
    ('firmware/btfw.env', 'BTFW_SHA'): hashlib.sha256(btfw).hexdigest(),
    ('bluez/bluez.env', 'BLUEZ_TAR'): 'bz.tar',
    ('bluez/bluez.env', 'BLUEZ_SHA'): hashlib.sha256(bluez).hexdigest(),
    ('firmware/kernel.env', 'BOOT_SHA'): hashlib.sha256(boot).hexdigest(),
    ('firmware/kernel.env', 'BOOT_SIZE'): str(len(boot)),
  }
  orig = m.env_val
  m.env_val = lambda f, name, pins=pins, orig=orig: pins.get((f, name), orig(f, name))


def test_runs_once_then_stamp_skips(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  sp = FakePage()
  assert m.main(lambda: sp) == 0
  assert runs(tmp_path) == ['--yes'] and sp.closed
  assert (tmp_path / 'data/stamp').read_text() == m.setup_key()
  assert m.main(lambda: FakePage()) == 0
  assert runs(tmp_path) == ['--yes']  # second boot: nothing to do


def test_stamp_changes_with_pins_agnos_and_slot(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  k = m.setup_key()
  (tmp_path / 'VERSION').write_text('20.7')
  assert m.setup_key() != k
  (tmp_path / 'VERSION').write_text('20.6')
  m.slot = lambda: '_b'
  assert m.setup_key() != k
  m.slot = lambda: '_a'
  assert m.setup_key() == k
  # every pin file is part of the key
  assert {'firmware/kernel.env', 'firmware/btfw.env', 'bluez/bluez.env', 'firmware/firmware.sha256'} <= set(m.KEY_FILES)
  for f in m.KEY_FILES:
    assert (HERE / f).is_file(), f


def test_pin_change_reruns(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'data/stamp').write_text('an older setup')
  m.main(lambda: FakePage())
  assert runs(tmp_path) == ['--yes']


def test_skip_on_disable_and_off_a_comma_4(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'data/disable').touch()
  assert m.main(lambda: FakePage()) == 0 and runs(tmp_path) == []
  assert not (tmp_path / 'data/stamp').exists()
  m = load(tmp_path, monkeypatch, model='comma tici')
  (tmp_path / 'data/disable').unlink()
  assert m.main(lambda: FakePage()) == 0 and runs(tmp_path) == []


@pytest.mark.parametrize('param', ['0', '1', None])
def test_disable_survives_boot_with_bt_off(tmp_path, monkeypatch, param):
  # disable is only ever the kill switch: never moved, whatever DpbBluetooth says
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'data/disable').touch()
  if param is not None:
    (tmp_path / 'DpbBluetooth').write_text(param)
  for _ in range(2):
    m.main(lambda: FakePage())
  assert (tmp_path / 'data/disable').exists() and not (tmp_path / 'data/bt_off').exists()
  assert runs(tmp_path) == [] and m.skip_reason(m.setup_key()) == 'disabled'


def test_no_network_falls_through_and_retries(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "[2/4] BT firmware"; echo "refusing: download failed: x" >&2; exit 75')
  assert m.main(lambda: FakePage()) == 0
  assert not (tmp_path / 'data/stamp').exists()
  log = (tmp_path / 'data/log').read_text()
  assert 'download failed, not counted' in log and 'download failed: x' in log
  # never counted: no Wi-Fi for many boots does not use up the tries
  for _ in range(4):
    m.main(lambda: FakePage())
  assert runs(tmp_path) == ['--yes'] * 5 and not (tmp_path / 'data/fails').exists()
  assert not (tmp_path / 'reboots').exists()


def test_gives_up_after_three_failures_per_setup(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='exit 1')
  for _ in range(5):
    m.main(lambda: FakePage())
  assert runs(tmp_path) == ['--yes'] * 3
  assert (tmp_path / 'data/fails').read_text() == f'{m.setup_key()} 3'
  assert 'gave up after 3 failed runs' in m.skip_reason(m.setup_key())
  # a new setup (pin, AGNOS or slot) gets its own three tries
  m.slot = lambda: '_b'
  m.main(lambda: FakePage())
  assert runs(tmp_path) == ['--yes'] * 4


def test_success_clears_the_fail_count(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'data/fails').write_text(f'{m.setup_key()} 2')
  m.main(lambda: FakePage())
  assert (tmp_path / 'data/stamp').exists() and not (tmp_path / 'data/fails').exists()


def test_hung_install_times_out(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='sleep 60')
  m.TIMEOUT_S = 0.5
  sp = FakePage()
  assert m.main(lambda: sp) == 0 and sp.closed
  assert 'timed out' in (tmp_path / 'data/log').read_text()
  assert not (tmp_path / 'data/stamp').exists()


def test_kernel_step_is_never_timed_out(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "[3/4] x"; echo "[4/4] kernel"; sleep 1.5; echo flashed')
  m.TIMEOUT_S = 0.3
  assert m.main(lambda: FakePage()) == 0
  log = (tmp_path / 'data/log').read_text()
  assert 'timed out' not in log and 'flashed' in log and (tmp_path / 'data/stamp').exists()


def test_kernel_step_is_waited_for_to_the_end(tmp_path, monkeypatch):
  # no stop after [4/4]: manager starts only once the kernel step is over
  monkeypatch.setenv('DPB_KERNEL_WAIT_S', '0.3')  # the old 60 min stop's knob, now ignored
  m = load(tmp_path, monkeypatch, install=f'echo "[4/4] kernel"; sleep 2; echo "  kernel: switching slot 98%"; echo done > {tmp_path}/finished')
  m.TIMEOUT_S = 0.3
  assert m.main(lambda: FakePage()) == 0
  assert (tmp_path / 'finished').exists() and (tmp_path / 'data/stamp').exists()
  assert 'switching slot 98%' in (tmp_path / 'data/log').read_text()
  assert not hasattr(m, 'KERNEL_WAIT_S') and not hasattr(m, 'STILL')


def test_timeout_sends_term_first(tmp_path, monkeypatch):
  # the installer gets SIGTERM (its EXIT trap tears apt down), SIGKILL only if it ignores that
  m = load(tmp_path, monkeypatch, install=f'trap "echo term > {tmp_path}/got; exit 143" TERM; echo "[2/4] x"; sleep 30 & wait')
  m.TIMEOUT_S = 0.3
  t0 = __import__('time').monotonic()
  m.main(lambda: FakePage())
  assert (tmp_path / 'got').read_text().strip() == 'term'
  assert __import__('time').monotonic() - t0 < 5  # did not need the 10 s SIGKILL wait


def test_reboots_only_after_a_flash(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "[4/4] kernel"; echo "  kernel: writing slot b 55%"', state='pending')
  sp = FakePage()
  m.main(lambda: sp)
  assert (tmp_path / 'reboots').read_text().splitlines() == ['reboot']
  assert not (tmp_path / 'data/stamp').exists()  # the new slot changes the key anyway
  assert sp.seen[-1] == 20 + 55 * 80 // 100
  for st in ('ok', 'off', 'failed', 'outdated'):
    d = tmp_path / st
    d.mkdir()
    m = load(d, monkeypatch, state=st)
    m.main(lambda: FakePage())
    assert not (d / 'reboots').exists() and (d / 'data/stamp').exists()


def test_installer_reboot_is_left_to_boot(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "REBOOT=$DPB_REBOOT"')
  m.main(lambda: FakePage())
  assert 'REBOOT=true' in (tmp_path / 'data/log').read_text()


def test_progress_bar_only_grows():
  spec = importlib.util.spec_from_file_location('dpb_boot2', HERE / 'boot.py')
  m = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(m)
  pct, seen = 0, []
  for ln in ('[1/4] last kernel flash', '[2/4] BT firmware', 'noise 99%', '[3/4] Bluetooth packages and services',
             '[4/4] kernel', '  kernel: downloading 8%', '  kernel: verifying 40', '  kernel: verifying 40%',
             '  kernel: switching slot 98%'):
    pct = m.progress(ln, pct)
    seen.append(pct)
  assert seen == sorted(seen) and seen[0] == 0 and seen[3] == 13 and seen[4] == 20 and seen[-1] == 98


def test_crash_never_stops_openpilot(tmp_path):
  r = subprocess.run(['python3', str(HERE / 'boot.py')], capture_output=True, text=True,
                     env={'PATH': '/usr/bin:/bin', 'DPB_DIR': str(tmp_path), 'DPB_BOOT_DIR': str(tmp_path), 'DPB_MODEL': str(tmp_path / 'none')})
  assert r.returncode == 0 and 'skip, not a comma 4' in r.stdout


def test_page_is_the_kernel_page():
  text = (HERE / 'boot.py').read_text()
  assert 'openpilot/system/dpbridge/kernel_page.py' in text and 'Spinner' not in text
  assert re.search(r'DPB_REBOOT="true"', text)


def test_unreachable_host_skips_without_counting(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  m.online = lambda: False
  for _ in range(4):
    assert m.main(lambda: FakePage()) == 0
  assert runs(tmp_path) == [] and not (tmp_path / 'data/fails').exists() and not (tmp_path / 'data/stamp').exists()
  assert 'github.com/ unreachable, not counted' in (tmp_path / 'data/log').read_text()
  m.online = lambda: True
  m.main(lambda: FakePage())
  assert runs(tmp_path) == ['--yes']


def test_offline_with_everything_on_data_still_installs(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer')  # a flash follows, so boot.img counts
  m.online = lambda: False
  pin_cache(m, tmp_path, write=False)
  (tmp_path / 'data/debs/fw.tar').write_bytes(b'fw')
  (tmp_path / 'data/debs/bz.tar').write_bytes(b'bz')
  m.main(lambda: FakePage())
  assert runs(tmp_path) == []  # boot.img missing: still needs the network
  (tmp_path / 'data/boot.img').write_bytes(b'boot')
  m.main(lambda: FakePage())
  assert runs(tmp_path) == ['--yes --accept-kernel']


def test_stale_cache_does_not_skip_the_offline_check(tmp_path, monkeypatch):
  # leftover files from an older pin must not count as cached
  m = load(tmp_path, monkeypatch, state='offer')
  m.online = lambda: False
  pin_cache(m, tmp_path)
  assert m.cached()
  (tmp_path / 'data/debs/fw.tar').write_bytes(b'old fw')
  assert not m.cached()
  m.main(lambda: FakePage())
  assert runs(tmp_path) == [] and 'unreachable, not counted' in (tmp_path / 'data/log').read_text()
  (tmp_path / 'data/debs/fw.tar').write_bytes(b'fw')
  (tmp_path / 'data/boot.img').write_bytes(b'bootXXXX')  # wrong size
  assert not m.cached()
  (tmp_path / 'data/boot.img').write_bytes(b'BOOT')  # same size, wrong sha
  assert not m.cached()
  m.main(lambda: FakePage())
  assert runs(tmp_path) == []
  # exist-only (the old cached() test) is not enough
  (tmp_path / 'data/debs/fw.tar').write_bytes(b'')
  (tmp_path / 'data/debs/bz.tar').write_bytes(b'')
  (tmp_path / 'data/boot.img').write_bytes(b'')
  assert not m.cached()


def test_cached_wrong_bluez_sha_is_not_cached(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  m.online = lambda: False
  pin_cache(m, tmp_path)
  (tmp_path / 'data/debs/bz.tar').write_bytes(b'old bz')
  assert not m.cached()
  m.main(lambda: FakePage())
  assert runs(tmp_path) == [] and 'unreachable, not counted' in (tmp_path / 'data/log').read_text()


def test_cached_empty_pins_and_missing_files_is_false(tmp_path, monkeypatch):
  # empty shas plus missing files compare "" == ""; the size check is allowed to pass so only the guard rejects it
  m = load(tmp_path, monkeypatch)
  pin_cache(m, tmp_path, write=False)
  orig = m.env_val
  m.env_val = lambda f, name, orig=orig: '' if name in ('BTFW_SHA', 'BLUEZ_SHA', 'BOOT_SHA') else orig(f, name)
  monkeypatch.setattr(m.os.path, 'getsize', lambda path: int(orig('firmware/kernel.env', 'BOOT_SIZE')))
  assert not m.cached()


def test_cached_boot_size_precheck(tmp_path, monkeypatch):
  # size is a fast path; this still fails if only the sha is trusted
  m = load(tmp_path, monkeypatch)
  pin_cache(m, tmp_path)
  (tmp_path / 'data/boot.img').write_bytes(b'bootXXXX')
  sha = {'fw.tar': hashlib.sha256(b'fw').hexdigest(),
         'bz.tar': hashlib.sha256(b'bz').hexdigest(),
         'boot.img': hashlib.sha256(b'boot').hexdigest()}
  m.file_sha = lambda path, sha=sha: sha[path.rsplit('/', 1)[-1]]
  assert not m.cached()


def test_stamped_boot_never_hashes_payloads(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  pin_cache(m, tmp_path)
  (tmp_path / 'data/stamp').write_text(m.setup_key())

  def boom(path):
    raise AssertionError(f'file_sha opened {path} on a stamped boot')

  m.file_sha = boom
  assert m.main(lambda: FakePage()) == 0
  assert runs(tmp_path) == []


def test_reachability_check_is_5_s(tmp_path, monkeypatch):
  import os
  load(tmp_path, monkeypatch)  # env only; the real online() from a fresh import
  spec = importlib.util.spec_from_file_location('dpb_boot2', HERE / 'boot.py')
  fresh = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(fresh)
  assert fresh.release_host() == 'https://github.com/'
  bin_ = tmp_path / 'bin'
  bin_.mkdir()
  (bin_ / 'curl').write_text(f'#!/bin/sh\necho "$*" > {tmp_path}/args\nexit ${{CURL_RC:-0}}\n')
  (bin_ / 'curl').chmod(0o755)
  monkeypatch.setenv('PATH', f'{bin_}:{os.environ["PATH"]}')
  assert fresh.online()
  assert (tmp_path / 'args').read_text().split() == ['-sI', '--max-time', '5', '-o', '/dev/null', 'https://github.com/']
  monkeypatch.setenv('CURL_RC', '28')
  assert not fresh.online()


def boot_sha(m):
  return m.env_val('firmware/kernel.env', 'BOOT_SHA')


def test_stock_kernel_asks_first_and_accept_flashes(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer')
  pg = FakePage('accept')
  m.main(lambda: pg)
  assert pg.asked == 1 and pg.closed and runs(tmp_path) == ['--yes --accept-kernel']
  assert (tmp_path / 'data/consent').read_text() == boot_sha(m) and 'kernel accepted' in (tmp_path / 'data/log').read_text()


def test_consent_is_once_per_kernel_image(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer', install='exit 75')  # a download failure, so every boot runs again
  (tmp_path / 'data/consent').write_text(boot_sha(m))
  pg = FakePage('later')
  m.main(lambda: pg)
  assert pg.asked == 0 and runs(tmp_path) == ['--yes --accept-kernel']
  (tmp_path / 'data/consent').write_text('an older image')
  m.main(lambda: pg)
  assert pg.asked == 1 and len(runs(tmp_path)) == 1 and (tmp_path / 'data/declined').exists()


def test_not_now_is_kept_until_settings_clears_it(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer')
  pg = FakePage('later')
  assert m.main(lambda: pg) == 0
  assert pg.asked == 1 and runs(tmp_path) == [] and not (tmp_path / 'data/fails').exists()
  assert (tmp_path / 'data/declined').exists() and not (tmp_path / 'data/consent').exists()
  for _ in range(3):
    m.main(lambda: pg)
  assert pg.asked == 1 and runs(tmp_path) == [] and m.skip_reason(m.setup_key()).startswith('kernel declined')
  (tmp_path / 'data/declined').unlink()  # what the Settings entry does, then a reboot
  m.main(lambda: FakePage('accept'))
  assert runs(tmp_path) == ['--yes --accept-kernel']


def test_no_answer_saves_nothing_and_asks_next_boot(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer')
  pg = FakePage('')  # the page process died
  m.main(lambda: pg)
  m.main(lambda: pg)
  assert pg.asked == 2 and runs(tmp_path) == []
  assert not (tmp_path / 'data/declined').exists() and not (tmp_path / 'data/consent').exists()


def test_no_question_without_a_stock_kernel(tmp_path, monkeypatch):
  for st in ('ok', 'outdated', 'off', 'failed', 'pending', 'no_space', 'unsupported_agnos'):
    d = tmp_path / st
    d.mkdir()
    m = load(d, monkeypatch, state=st)
    pg = FakePage('later')
    m.main(lambda pg=pg: pg)
    assert pg.asked == 0 and runs(d) == ['--yes'], st


def test_page_shows_step_names(tmp_path, monkeypatch):
  steps = ('[2/4] BT firmware', '[4/4] kernel', '  kernel: downloading 8%', '  kernel: writing slot b 55%', '  kernel: rebooting 100%')
  m = load(tmp_path, monkeypatch, install='; '.join(f'echo "{s}"' for s in steps))
  pg = FakePage()
  m.main(lambda: pg)
  names = [n for i, n in enumerate(pg.names) if i == 0 or n != pg.names[i - 1]]
  assert names == ['installing', 'downloading', 'writing slot b', 'rebooting'] and pg.seen[-1] == 100


def test_failure_is_shown_then_openpilot_starts(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer', install='exit 1')
  pg = FakePage()
  assert m.main(lambda: pg) == 0
  assert pg.notes == [('kernel not\ninstalled', 'openpilot is starting')] and pg.closed
  (tmp_path / 'x').mkdir()
  m = load(tmp_path / 'x', monkeypatch, install='exit 75')
  pg = FakePage()
  m.main(lambda: pg)
  assert pg.notes == [('download\nfailed', 'tries next boot')]


FAKE_PAGE = '''import sys
for ln in sys.stdin:
  open(sys.argv[1], "a").write(ln)
  if ln.strip() == "ask":
    print(sys.argv[2], flush=True)
'''


def test_page_client_talks_to_the_page_process(tmp_path, monkeypatch):
  import sys
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'page.py').write_text(FAKE_PAGE)
  real = m.subprocess.Popen
  for reply, want in (('later', 'later'), ('accept', 'accept'), ('noise', '')):
    got = tmp_path / f'got_{reply}'
    monkeypatch.setattr(m.subprocess, 'Popen', lambda cmd, _p=real, _got=got, _reply=reply, **kw:
                        _p([sys.executable, str(tmp_path / 'page.py'), str(_got), _reply], **kw))
    pg = m.Page()
    pg.connecting(85.2)
    pg.progress(64, 'writing slot b')
    pg.note('kernel not\ninstalled', 'openpilot is starting')
    a = pg.ask() if reply != 'noise' else (pg._p.stdin.close(), pg.ask())[1]
    pg.close()
    assert a == want
    if reply == 'later':
      assert got.read_text().splitlines() == ['wait 85', 'step 64 writing slot b', 'note kernel not\\ninstalled|openpilot is starting', 'ask']
  monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **kw: (_ for _ in ()).throw(OSError('no display')))
  pg = m.Page()
  assert pg.ask() == '' and pg.close() is None  # no page: no answer, so no flash


def fake_clock(m, up_at=None):
  # online() answers from up_at seconds on; each check costs 1 s
  t = [0.0]
  checks = []

  def online():
    checks.append(t[0])
    t[0] += 1
    return up_at is not None and checks[-1] >= up_at

  m.clock = lambda: t[0]
  m.nap = lambda s: t.__setitem__(0, t[0] + s)
  m.online = online
  m.NET_WAIT_S = 90.0
  return checks


def test_waits_for_the_network_then_installs(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  checks = fake_clock(m, up_at=20)
  pg = FakePage()
  m.main(lambda: pg)
  assert checks == [0, 5, 10, 15, 20] and runs(tmp_path) == ['--yes']
  assert pg.waits == [90, 85, 80, 75, 70]


def test_no_network_after_90_s_skips_uncounted(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  checks = fake_clock(m)
  pg = FakePage()
  assert m.main(lambda: pg) == 0
  assert checks == list(range(0, 95, 5)) and runs(tmp_path) == [] and not (tmp_path / 'data/fails').exists()
  assert 'unreachable, not counted (waited 90 s)' in (tmp_path / 'data/log').read_text()
  assert pg.notes == [('no network,\nskipped', 'tries next boot')]


def test_no_wait_when_everything_is_on_data(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer')
  pin_cache(m, tmp_path)
  checks = fake_clock(m)
  m.main(lambda: FakePage())
  assert checks == [] and runs(tmp_path) == ['--yes --accept-kernel']


def test_running_kernel_needs_no_boot_img(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='ok')
  pin_cache(m, tmp_path)
  (tmp_path / 'data/boot.img').unlink()
  checks = fake_clock(m)
  m.main(lambda: FakePage())
  assert checks == [] and runs(tmp_path) == ['--yes'] and not m.cached()


def test_network_wait_defaults(monkeypatch):
  monkeypatch.delenv('DPB_NET_WAIT_S', raising=False)
  spec = importlib.util.spec_from_file_location('dpb_boot3', HERE / 'boot.py')
  m = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(m)
  assert m.NET_WAIT_S == 90 and m.NET_STEP_S == 5


def test_no_answer_powers_off_and_saves_nothing(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer')
  (tmp_path / 'poweroff').write_text(f'echo off >> {tmp_path}/offs\n')
  m.POWEROFF, m.HALT_S = ['bash', str(tmp_path / 'poweroff')], 0
  pg = FakePage(None)
  assert m.main(lambda: pg) == 0
  assert (tmp_path / 'offs').read_text().splitlines() == ['off'] and pg.closed and runs(tmp_path) == []
  assert sorted(p.name for p in (tmp_path / 'data').iterdir()) == ['log']  # no consent, declined, stamp or fails
  assert 'not answered in 600 s, powering off' in (tmp_path / 'data/log').read_text()
  assert not (tmp_path / 'reboots').exists()
  m.main(lambda: pg)
  assert pg.asked == 2  # asks again next boot


def test_page_died_still_boots_without_poweroff(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, state='offer')
  m.POWEROFF = ['bash', '-c', f'echo off >> {tmp_path}/offs']
  assert m.main(lambda: FakePage('')) == 0
  assert not (tmp_path / 'offs').exists() and runs(tmp_path) == [] and not (tmp_path / 'data/declined').exists()


def test_ask_deadline(tmp_path, monkeypatch):
  import sys
  import time
  m = load(tmp_path, monkeypatch)
  assert m.ASK_S == 600 and m.POWEROFF == ['sudo', 'poweroff']
  m.ASK_S = 0.5
  (tmp_path / 'page.py').write_text(FAKE_PAGE)
  real = m.subprocess.Popen
  monkeypatch.setattr(m.subprocess, 'Popen', lambda cmd, **kw: real([sys.executable, str(tmp_path / 'page.py'), str(tmp_path / 'got'), 'noise'], **kw))
  pg = m.Page()
  t0 = time.monotonic()
  assert pg.ask() is None and time.monotonic() - t0 < 5  # alive but silent: the deadline, not a hang
  pg.close()

