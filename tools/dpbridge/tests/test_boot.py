# boot.py: the first-boot run of the installer before manager.
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


class FakeSpinner:
  def __init__(self):
    self.seen, self.closed = [], False

  def update_progress(self, cur, total):
    self.seen.append(round(100 * cur / total))

  def close(self):
    self.closed = True


def load(tmp_path, monkeypatch, install='echo "[1/4] x"; exit 0', state='ok', model='comma mici', slot='_a'):
  for k, v in (('DPB_DIR', tmp_path / 'data'), ('DPB_BOOT_DIR', tmp_path / 'data'), ('DPB_MODEL', tmp_path / 'model'), ('DPB_VERSION', tmp_path / 'VERSION'),
               ('DPB_BOOT_TIMEOUT_S', '5'),
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
  return m


def runs(tmp_path):
  p = tmp_path / 'runs'
  return p.read_text().splitlines() if p.exists() else []


def test_runs_once_then_stamp_skips(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  sp = FakeSpinner()
  assert m.main(lambda: sp) == 0
  assert runs(tmp_path) == ['--yes'] and sp.closed
  assert (tmp_path / 'data/stamp').read_text() == m.setup_key()
  assert m.main(lambda: FakeSpinner()) == 0
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
  m.main(lambda: FakeSpinner())
  assert runs(tmp_path) == ['--yes']


def test_skip_on_disable_and_off_a_comma_4(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'data/disable').touch()
  assert m.main(lambda: FakeSpinner()) == 0 and runs(tmp_path) == []
  assert not (tmp_path / 'data/stamp').exists()
  m = load(tmp_path, monkeypatch, model='comma tici')
  (tmp_path / 'data/disable').unlink()
  assert m.main(lambda: FakeSpinner()) == 0 and runs(tmp_path) == []


@pytest.mark.parametrize('param', ['0', '1', None])
def test_disable_survives_boot_with_bt_off(tmp_path, monkeypatch, param):
  # disable is only ever the kill switch: never moved, whatever DpbBluetooth says
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'data/disable').touch()
  if param is not None:
    (tmp_path / 'DpbBluetooth').write_text(param)
  for _ in range(2):
    m.main(lambda: FakeSpinner())
  assert (tmp_path / 'data/disable').exists() and not (tmp_path / 'data/bt_off').exists()
  assert runs(tmp_path) == [] and m.skip_reason(m.setup_key()) == 'disabled'


def test_no_network_falls_through_and_retries(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "[2/4] BT firmware"; echo "refusing: download failed: x" >&2; exit 75')
  assert m.main(lambda: FakeSpinner()) == 0
  assert not (tmp_path / 'data/stamp').exists()
  log = (tmp_path / 'data/log').read_text()
  assert 'download failed, not counted' in log and 'download failed: x' in log
  # never counted: no Wi-Fi for many boots does not use up the tries
  for _ in range(4):
    m.main(lambda: FakeSpinner())
  assert runs(tmp_path) == ['--yes'] * 5 and not (tmp_path / 'data/fails').exists()
  assert not (tmp_path / 'reboots').exists()


def test_gives_up_after_three_failures_per_setup(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='exit 1')
  for _ in range(5):
    m.main(lambda: FakeSpinner())
  assert runs(tmp_path) == ['--yes'] * 3
  assert (tmp_path / 'data/fails').read_text() == f'{m.setup_key()} 3'
  assert 'gave up after 3 failed runs' in m.skip_reason(m.setup_key())
  # a new setup (pin, AGNOS or slot) gets its own three tries
  m.slot = lambda: '_b'
  m.main(lambda: FakeSpinner())
  assert runs(tmp_path) == ['--yes'] * 4


def test_success_clears_the_fail_count(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch)
  (tmp_path / 'data/fails').write_text(f'{m.setup_key()} 2')
  m.main(lambda: FakeSpinner())
  assert (tmp_path / 'data/stamp').exists() and not (tmp_path / 'data/fails').exists()


def test_hung_install_times_out(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='sleep 60')
  m.TIMEOUT_S = 0.5
  sp = FakeSpinner()
  assert m.main(lambda: sp) == 0 and sp.closed
  assert 'timed out' in (tmp_path / 'data/log').read_text()
  assert not (tmp_path / 'data/stamp').exists()


def test_kernel_step_is_never_timed_out(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "[3/4] x"; echo "[4/4] kernel"; sleep 1.5; echo flashed')
  m.TIMEOUT_S = 0.3
  assert m.main(lambda: FakeSpinner()) == 0
  log = (tmp_path / 'data/log').read_text()
  assert 'timed out' not in log and 'flashed' in log and (tmp_path / 'data/stamp').exists()


def test_long_kernel_step_stops_waiting_without_a_kill(tmp_path, monkeypatch):
  # 60 min after [4/4] boot.py lets manager start; the installer keeps running and keeps writing its output
  m = load(tmp_path, monkeypatch, install=f'echo "[4/4] kernel"; sleep 2; echo "  kernel: switching slot 98%"; echo done > {tmp_path}/finished')
  m.KERNEL_WAIT_S = 0.5
  t0 = __import__('time').monotonic()
  assert m.main(lambda: FakeSpinner()) == 0
  assert __import__('time').monotonic() - t0 < 1.8
  assert 'kernel step still running' in (tmp_path / 'data/log').read_text()
  assert not (tmp_path / 'data/stamp').exists() and not (tmp_path / 'data/fails').exists()
  assert not (tmp_path / 'reboots').exists()
  deadline = __import__('time').monotonic() + 5
  while not (tmp_path / 'finished').exists() and __import__('time').monotonic() < deadline:
    __import__('time').sleep(0.1)
  assert (tmp_path / 'finished').exists()  # not killed, no broken pipe
  assert 'switching slot 98%' in (tmp_path / 'data/install.out').read_text()


def test_timeout_sends_term_first(tmp_path, monkeypatch):
  # the installer gets SIGTERM (its EXIT trap tears apt down), SIGKILL only if it ignores that
  m = load(tmp_path, monkeypatch, install=f'trap "echo term > {tmp_path}/got; exit 143" TERM; echo "[2/4] x"; sleep 30 & wait')
  m.TIMEOUT_S = 0.3
  t0 = __import__('time').monotonic()
  m.main(lambda: FakeSpinner())
  assert (tmp_path / 'got').read_text().strip() == 'term'
  assert __import__('time').monotonic() - t0 < 5  # did not need the 10 s SIGKILL wait


def test_reboots_only_after_a_flash(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "[4/4] kernel"; echo "  kernel: writing slot b 55%"', state='pending')
  sp = FakeSpinner()
  m.main(lambda: sp)
  assert (tmp_path / 'reboots').read_text().splitlines() == ['reboot']
  assert not (tmp_path / 'data/stamp').exists()  # the new slot changes the key anyway
  assert sp.seen[-1] == 20 + 55 * 80 // 100
  for st in ('ok', 'off', 'failed', 'outdated'):
    d = tmp_path / st
    d.mkdir()
    m = load(d, monkeypatch, state=st)
    m.main(lambda: FakeSpinner())
    assert not (d / 'reboots').exists() and (d / 'data/stamp').exists()


def test_installer_reboot_is_left_to_boot(tmp_path, monkeypatch):
  m = load(tmp_path, monkeypatch, install='echo "REBOOT=$DPB_REBOOT"')
  m.main(lambda: FakeSpinner())
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


def test_spinner_is_comma_s():
  text = (HERE / 'boot.py').read_text()
  assert 'from openpilot.common.spinner import Spinner' in text
  assert re.search(r'DPB_REBOOT="true"', text)
