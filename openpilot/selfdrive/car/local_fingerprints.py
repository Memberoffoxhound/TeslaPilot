"""Locally learned Tesla EPS firmware. Lives in /data so it survives updates."""
from pathlib import Path

from opendbc.car.tesla import fingerprint_overlay

PATH = Path("/data/teslapilot/fingerprints/tesla-fw-v1.json")


def load(path: Path = PATH) -> dict:
  return fingerprint_overlay.load(path)


def save(platform, car_fw, path: Path = PATH) -> None:
  fingerprint_overlay.save(platform, car_fw, path)
