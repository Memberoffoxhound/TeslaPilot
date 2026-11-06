"""vehicle_profile: make detection and OEM stock badge map."""
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.car.vehicle_profile import MAKES, make, stock_make


def CP(brand, fingerprint=""):
  return SimpleNamespace(brand=brand, carFingerprint=fingerprint)


@pytest.mark.parametrize("cp, expect", [
  (None, "generic"),
  (CP(""), "generic"),
  (CP("mock"), "generic"),
  (CP("tesla", "TESLA_MODEL_3"), "tesla"),
  (CP("hyundai", "KIA_K5_2021"), "kia"),
  (CP("hyundai", "KIA_NIRO_EV"), "kia"),
  (CP("hyundai", "HYUNDAI_SONATA"), "generic"),
  (CP("hyundai", "GENESIS_G70"), "generic"),
  (CP("toyota", "TOYOTA_COROLLA"), "generic"),
])
def test_make(cp, expect):
  assert make(cp) == expect


def test_oem_labels_and_assets():
  assert MAKES["tesla"].stock_label == "TACC"
  assert MAKES["kia"].stock_label == "SCC"
  assert MAKES["generic"].stock_label == "ACC"
  assert MAKES["generic"].text_rows == ("STOCK", "ACC")
  assert MAKES["generic"].logo is None
  assert MAKES["generic"].logo_wh == (50, 48)
  assert MAKES["tesla"].logo.endswith("tesla_t.png")
  assert MAKES["kia"].logo.endswith("kia.png")
  assert MAKES["kia"].logo_wh == (120, 48)
  assert MAKES["kia"].letter_sz == 22
  assert MAKES["kia"].col_w == 22
  assert MAKES["tesla"].letter_sz == 11
  assert MAKES["tesla"].col_w == 16


def test_stock_make_follows_cp():
  assert stock_make(CP("tesla", "TESLA_MODEL_3")).stock_label == "TACC"
  assert stock_make(CP("hyundai", "KIA_K5_2021")).stock_label == "SCC"
  assert stock_make(CP("toyota", "TOYOTA_COROLLA")).text_rows == ("STOCK", "ACC")
