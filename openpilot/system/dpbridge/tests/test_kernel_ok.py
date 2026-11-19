import pytest

from openpilot.system.dpbridge import kernel_ok


@pytest.fixture
def k(tmp_path, monkeypatch):
  monkeypatch.setattr(kernel_ok, "WCN", str(tmp_path / "wcn3990"))
  kernel_ok.bt_kernel.cache_clear()
  yield tmp_path
  kernel_ok.bt_kernel.cache_clear()


def test_hidden_on_stock(k):
  assert not kernel_ok.bt_kernel()


def test_shown_with_marker(k):
  (k / "wcn3990").write_text("Y\n")
  assert kernel_ok.bt_kernel()


def test_shown_on_an_outdated_dpbridge_kernel(k):
  # BT runs on any dpbridge build (radio.sh starts it), so its toggle must be there to turn it off
  (k / "wcn3990").write_text("Y\n")
  (k / "running").write_text("this-boot outdated\n")
  assert kernel_ok.bt_kernel()
  assert "running" not in open(kernel_ok.__file__).read()


def test_bad_path_never_crashes_the_ui(k, monkeypatch):
  monkeypatch.setattr(kernel_ok, "WCN", "/bad\0path")
  assert kernel_ok.bt_kernel() is False


def test_checked_once(k):
  assert not kernel_ok.bt_kernel()
  (k / "wcn3990").write_text("Y\n")
  assert not kernel_ok.bt_kernel()  # same boot, same answer


def test_path_matches_kernel_sh():
  from pathlib import Path
  sh = (Path(kernel_ok.__file__).resolve().parents[3] / "tools/dpbridge/kernel.sh").read_text()
  assert f"WCN=${{DPB_WCN:-{kernel_ok.WCN}}}" in sh
