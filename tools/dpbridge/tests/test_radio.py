import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
RADIO = HERE / "radio.sh"


def run_radio(tmp_path, param, hci0=False, off=False):
  log = tmp_path / "sysctl.log"
  stub = tmp_path / "systemctl"
  stub.write_text(f"#!/bin/bash\necho \"$*\" >>\"{log}\"\n")
  stub.chmod(0o755)
  env = dict(os.environ,
             DPBRIDGE_DIR=str(tmp_path / "dpb"),
             DPB_BLUETOOTH_PARAM=str(param),
             DPB_HCI0=str(tmp_path / ("hci0" if hci0 else "no-hci0")),
             DPB_SYSTEMCTL=str(stub),
             DPB_UNITS="dpbridge-bt bluetooth")
  if off:
    (tmp_path / "dpb").mkdir(exist_ok=True)
    (tmp_path / "dpb" / "bt_off").write_text("")
  if hci0:
    (tmp_path / "hci0").write_text("")
  r = subprocess.run(["bash", str(RADIO), "--once"], env=env, capture_output=True, text=True)
  assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
  actions = log.read_text().splitlines() if log.exists() else []
  return actions, tmp_path / "dpb" / "bt_off"


def test_off_stops_and_writes_bt_off(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("0")
  actions, off = run_radio(tmp_path, param)
  assert any(a.startswith("stop ") for a in actions)
  assert off.is_file() and not (tmp_path / "dpb/disable").exists()  # not the install kill switch


def test_on_starts_and_removes_bt_off_only(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("1")
  (tmp_path / "dpb").mkdir()
  (tmp_path / "dpb" / "bt_off").write_text("")
  (tmp_path / "dpb" / "disable").write_text("")
  actions, off = run_radio(tmp_path, param)
  assert any(a.startswith("start ") for a in actions)
  assert not off.exists() and (tmp_path / "dpb/disable").exists()  # the kill switch is the user's


def test_seed_on_when_hci0_already_up(tmp_path):
  param = tmp_path / "DpbBluetooth"
  actions, off = run_radio(tmp_path, param, hci0=True)
  assert param.read_text() == "1"
  assert any(a.startswith("start ") for a in actions)
  assert not off.exists()


def test_seed_off_after_bt_off(tmp_path):
  param = tmp_path / "DpbBluetooth"
  actions, off = run_radio(tmp_path, param, hci0=True, off=True)
  assert param.read_text() == "0" and any(a.startswith("stop ") for a in actions)


def test_disable_survives_radio_with_the_toggle_off(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("0")
  (tmp_path / "dpb").mkdir()
  (tmp_path / "dpb" / "disable").write_text("")
  actions, off = run_radio(tmp_path, param)
  assert (tmp_path / "dpb/disable").exists() and off.exists()  # bt_off written, kill switch kept


def test_disable_with_the_toggle_on_is_left_alone(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("1")
  (tmp_path / "dpb").mkdir()
  (tmp_path / "dpb" / "disable").write_text("")
  run_radio(tmp_path, param)
  assert (tmp_path / "dpb/disable").exists()


def test_bt_unit_and_deliver_use_bt_off():
  inst = (HERE / "install_userspace.sh").read_text()
  assert "ConditionPathExists=!$DIR/bt_off" in inst and "ConditionPathExists=!$DIR/disable" not in inst
  dl = (HERE / "mac/deliver.sh").read_text()
  assert "rm -f $REMOTE/bt_off" in dl and "touch $REMOTE/bt_off" in dl and "$REMOTE/disable" not in dl
  # disable is read by the installer side only
  assert "disable" not in (HERE / "radio.sh").read_text().replace("shellcheck disable", "").replace("$DIR/disable is only", "")


def watch(tmp_path, param, hci0, settle="2", secs=1.5):
  log = tmp_path / "sysctl.log"
  stub = tmp_path / "systemctl"
  stub.write_text(f"#!/bin/bash\necho \"$*\" >>\"{log}\"\n")
  stub.chmod(0o755)
  if hci0:
    (tmp_path / "hci0").write_text("")
  env = dict(os.environ, DPBRIDGE_DIR=str(tmp_path / "dpb"), DPB_BLUETOOTH_PARAM=str(param),
             DPB_HCI0=str(tmp_path / ("hci0" if hci0 else "no-hci0")), DPB_SYSTEMCTL=str(stub),
             DPB_UNITS="dpbridge-bt bluetooth", DPB_SETTLE_S=settle, DPB_TICK_S="0.1")
  p = subprocess.Popen(["bash", str(RADIO), "--watch"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
  try:
    p.wait(timeout=secs)
  except subprocess.TimeoutExpired:
    p.kill()  # like a panic: the marker stays if it has not settled
  out = p.communicate()[0]
  return (log.read_text().splitlines() if log.exists() else []), out


def test_two_starts_that_never_settled_switch_bluetooth_off(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("1")
  mark = tmp_path / "dpb" / "bt_boot"
  reason = tmp_path / "dpb" / "bt_reason"
  # boots 1 and 2: started, killed before hci0 came up
  for n in (1, 2):
    actions, _ = watch(tmp_path, param, hci0=False, secs=0.5)
    assert any(a.startswith("start ") for a in actions) and mark.read_text().strip() == str(n)
    assert param.read_text() == "1" and not reason.exists()
    (tmp_path / "sysctl.log").unlink()
  # boot 3: off instead of starting again, with a reason for Settings
  actions, out = watch(tmp_path, param, hci0=False, secs=0.5)
  assert param.read_text() == "0" and not mark.exists() and "never settled" in out
  assert not any(a.startswith("start ") for a in actions)
  assert reason.read_text().strip() == "off: did not start twice"
  # switched on again from Settings: the reason goes, a fresh count starts
  param.write_text("1")
  watch(tmp_path, param, hci0=False, secs=0.5)
  assert not reason.exists() and mark.read_text().strip() == "1"


def test_old_empty_marker_counts_as_one(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("1")
  (tmp_path / "dpb").mkdir()
  (tmp_path / "dpb" / "bt_boot").write_text("")
  actions, _ = watch(tmp_path, param, hci0=False, secs=0.5)
  assert any(a.startswith("start ") for a in actions) and (tmp_path / "dpb/bt_boot").read_text().strip() == "2"


def test_settled_start_clears_the_marker(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("1")
  watch(tmp_path, param, hci0=True, settle="3", secs=1.5)
  assert not (tmp_path / "dpb" / "bt_boot").exists() and param.read_text() == "1"
