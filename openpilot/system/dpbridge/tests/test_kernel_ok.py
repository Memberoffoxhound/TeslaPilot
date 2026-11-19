import pytest

from openpilot.system.dpbridge import kernel_ok

BOOT = "1b2c3d4e-0000-4000-8000-000000000001"


@pytest.fixture
def k(tmp_path, monkeypatch):
  monkeypatch.setattr(kernel_ok, "WCN", str(tmp_path / "wcn3990"))
  monkeypatch.setattr(kernel_ok, "RUNNING", str(tmp_path / "running"))
  monkeypatch.setattr(kernel_ok, "BOOT_ID", str(tmp_path / "boot_id"))
  (tmp_path / "boot_id").write_text(BOOT + "\n")
  kernel_ok.bt_kernel.cache_clear()
  yield tmp_path
  kernel_ok.bt_kernel.cache_clear()


def test_hidden_on_stock(k):
  assert not kernel_ok.bt_kernel()


def test_shown_with_marker(k):
  (k / "wcn3990").write_text("Y\n")
  assert kernel_ok.bt_kernel()


def test_shown_with_marker_and_ok(k):
  (k / "wcn3990").write_text("Y\n")
  (k / "running").write_text(f"{BOOT} ok\n")
  assert kernel_ok.bt_kernel()


def test_hidden_on_an_outdated_dpbridge_kernel(k):
  (k / "wcn3990").write_text("Y\n")
  (k / "running").write_text(f"{BOOT} outdated\n")
  assert not kernel_ok.bt_kernel()


def test_outdated_from_an_earlier_boot_is_ignored(k):
  (k / "wcn3990").write_text("Y\n")
  (k / "running").write_text("another-boot outdated\n")
  assert kernel_ok.bt_kernel()


def test_checked_once(k):
  assert not kernel_ok.bt_kernel()
  (k / "wcn3990").write_text("Y\n")
  assert not kernel_ok.bt_kernel()  # same boot, same answer


def test_path_matches_kernel_sh():
  from pathlib import Path
  sh = (Path(kernel_ok.__file__).resolve().parents[3] / "tools/dpbridge/kernel.sh").read_text()
  assert f"WCN=${{DPB_WCN:-{kernel_ok.WCN}}}" in sh
  assert f"BOOT_ID=${{DPB_BOOT_ID:-{kernel_ok.BOOT_ID}}}" in sh
  assert 'K=$DIR/kernel' in sh and '"$K/running"' in sh and kernel_ok.RUNNING == "/data/dpbridge/kernel/running"
  assert 'echo "$id ok" > "$K/running"' in sh and 'echo "$id outdated" > "$K/running"' in sh
