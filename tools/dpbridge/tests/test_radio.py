import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
RADIO = HERE / "radio.sh"


def run_radio(tmp_path, param, hci0=False, disable=False):
  log = tmp_path / "sysctl.log"
  stub = tmp_path / "systemctl"
  stub.write_text("#!/bin/bash\necho \"$*\" >>\"%s\"\n" % log)
  stub.chmod(0o755)
  env = dict(os.environ,
             DPBRIDGE_DIR=str(tmp_path / "dpb"),
             DPB_BLUETOOTH_PARAM=str(param),
             DPB_HCI0=str(tmp_path / ("hci0" if hci0 else "no-hci0")),
             DPB_SYSTEMCTL=str(stub),
             DPB_UNITS="dpbridge-bt bluetooth")
  if disable:
    (tmp_path / "dpb").mkdir(exist_ok=True)
    (tmp_path / "dpb" / "disable").write_text("")
  if hci0:
    (tmp_path / "hci0").write_text("")
  r = subprocess.run(["bash", str(RADIO), "--once"], env=env, capture_output=True, text=True)
  assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
  actions = log.read_text().splitlines() if log.exists() else []
  return actions, tmp_path / "dpb" / "disable"


def test_off_stops_and_writes_disable(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("0")
  actions, disable = run_radio(tmp_path, param)
  assert any(a.startswith("stop ") for a in actions)
  assert disable.is_file()


def test_on_starts_and_removes_disable(tmp_path):
  param = tmp_path / "DpbBluetooth"
  param.write_text("1")
  (tmp_path / "dpb").mkdir()
  (tmp_path / "dpb" / "disable").write_text("")
  actions, disable = run_radio(tmp_path, param)
  assert any(a.startswith("start ") for a in actions)
  assert not disable.exists()


def test_seed_on_when_hci0_already_up(tmp_path):
  param = tmp_path / "DpbBluetooth"
  actions, disable = run_radio(tmp_path, param, hci0=True)
  assert param.read_text() == "1"
  assert any(a.startswith("start ") for a in actions)
  assert not disable.exists()
