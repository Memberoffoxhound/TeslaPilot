import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from opendbc.car import car_helpers as ch
from opendbc.car.structs import CarParams
from opendbc.car.tesla import fingerprint_overlay as fo
from opendbc.car.tesla.values import CAR
from openpilot.selfdrive.car import local_fingerprints as lf

FW = b"TeMYG4_Main_0.0.0 (99),E4H099.01.0"
P = str(CAR.TESLA_MODEL_3)


def capture(fw=FW):
  return [SimpleNamespace(brand="tesla", logging=False, ecu=fo.Ecu.eps, address=0x730, subAddress=0, fwVersion=fw)]


def test_save_load_match(tmp_path):
  path = tmp_path / "fw.json"
  fo.save(P, capture(), path)
  fo.save(P, capture(), path)
  assert json.loads(path.read_text()) == {P: [FW.hex()]}
  assert fo.load(path) == {P: {fo.EPS: [FW]}}
  assert lf.load(path) == fo.load(path)
  assert str(lf.PATH) == "/data/teslapilot/fingerprints/tesla-fw-v1.json"
  path.unlink()
  assert fo.load(path) == {}


@pytest.mark.parametrize("data", [[], {"TESLA_MODEL_X": [FW.hex()]}, {P: "wrong"}, {P: ["zz"]},
                                   {P: ["00"]}, {P: [FW.hex()] * 65}, {P: [FW.hex()], str(CAR.TESLA_MODEL_Y): [FW.hex()]}])
def test_invalid_overlay(tmp_path, data):
  with pytest.raises((TypeError, ValueError)):
    fo.validate(data)
  path = tmp_path / "fw.json"
  path.write_text(json.dumps(data))
  assert fo.load(path) == {}


def test_no_response_and_conflict(tmp_path):
  path = tmp_path / "fw.json"
  with pytest.raises(ValueError):
    fo.save(P, [], path)
  known_y = fo.FW_VERSIONS[CAR.TESLA_MODEL_Y][fo.EPS][0]
  with pytest.raises(ValueError):
    fo.save(P, capture(known_y), path)
  assert not path.exists()


def test_catalog():
  choices = fo.catalog()
  assert choices == sorted(choices, reverse=True)
  assert {y for y, _, _ in choices} == set(range(2019, 2027))
  assert {p for y, p, _ in choices if y == 2026} == set(fo.PLATFORMS)
  assert all(p != str(CAR.TESLA_MODEL_X) for _, p, _ in choices)


@pytest.mark.parametrize("candidate", [None, "TOYOTA_COROLLA_TSS2"])
def test_no_pin_or_stale_firmware(monkeypatch, candidate):
  monkeypatch.delenv("FINGERPRINT", raising=False)
  monkeypatch.delenv("SKIP_FW_QUERY", raising=False)
  monkeypatch.setattr(ch, "get_vin", lambda *a: (0, 0, ch.VIN_UNKNOWN))
  monkeypatch.setattr(ch, "get_present_ecus", lambda *a: set())
  monkeypatch.setattr(ch, "get_fw_versions_ordered", lambda *a: [])
  monkeypatch.setattr(ch, "can_fingerprint", lambda *a: (candidate, {}))
  cached = SimpleNamespace(brand="tesla", carVin=ch.VIN_UNKNOWN, carFw=capture())
  result = ch.fingerprint(lambda: None, lambda m: None, lambda b: None, cached, {})
  assert result[0] == candidate and result[3] == []


def test_stock_wins_over_local(monkeypatch):
  monkeypatch.setenv("FINGERPRINT", "TOYOTA_COROLLA_TSS2")
  monkeypatch.setenv("SKIP_FW_QUERY", "1")
  monkeypatch.setattr(ch, "can_fingerprint", lambda *a: (None, {}))
  monkeypatch.setattr(ch, "match_fw_to_car_exact", lambda *a, **k: pytest.fail("stock result must win"))
  result = ch.fingerprint(lambda: None, lambda m: None, lambda b: None, None, {P: {fo.EPS: [FW]}})
  assert result[0] == "TOYOTA_COROLLA_TSS2" and result[4] == CarParams.FingerprintSource.fixed


@pytest.mark.parametrize("fw, expected", [(FW, P), (b"different", None)])
def test_local_database_used_after_stock_miss(monkeypatch, tmp_path, fw, expected):
  path = tmp_path / "fw.json"
  fo.save(P, capture(), path)
  monkeypatch.delenv("FINGERPRINT", raising=False)
  monkeypatch.delenv("SKIP_FW_QUERY", raising=False)
  monkeypatch.setattr(ch, "get_vin", lambda *a: (0, 0, ch.VIN_UNKNOWN))
  monkeypatch.setattr(ch, "get_present_ecus", lambda *a: set())
  monkeypatch.setattr(ch, "get_fw_versions_ordered", lambda *a: capture(fw))
  monkeypatch.setattr(ch, "can_fingerprint", lambda *a: (None, {}))
  result = ch.fingerprint(lambda: None, lambda m: None, lambda b: None, None, lf.load(path))
  assert result[0] == expected
  if expected:
    assert result[4] == CarParams.FingerprintSource.fw


def test_card_passes_local_firmware():
  src = (Path(__file__).parents[1] / "card.py").read_text()
  assert "local_fingerprints.load()" in src
