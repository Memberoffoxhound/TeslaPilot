import json
import os
from pathlib import Path

PATH = "/dev/shm/dpbridge-radio.json"


def from_devices(devices: list[dict]) -> dict:
  connected = [d for d in devices if d.get("connected")]
  name = ""
  if connected:
    name = str(connected[0].get("name") or connected[0].get("mac") or "")
  return {"connected": bool(connected), "name": name}


def write(devices: list[dict], path: str | None = None) -> dict:
  st = from_devices(devices)
  dest = Path(PATH if path is None else path)
  try:
    if dest.is_file() and json.loads(dest.read_text()) == st:
      return st
  except (OSError, ValueError, TypeError):
    pass
  dest.parent.mkdir(parents=True, exist_ok=True)
  tmp = dest.with_suffix(dest.suffix + ".tmp")
  tmp.write_text(json.dumps(st, separators=(",", ":")))
  os.replace(tmp, dest)
  return st


def read(path: str | None = None) -> dict:
  try:
    st = json.loads(Path(PATH if path is None else path).read_text())
    return {"connected": bool(st.get("connected")), "name": str(st.get("name") or "")}
  except (OSError, ValueError, TypeError):
    return {"connected": False, "name": ""}
