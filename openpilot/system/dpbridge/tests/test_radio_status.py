from openpilot.system.dpbridge import radio_status


def test_from_devices_picks_first_connected():
  st = radio_status.from_devices([
    {"mac": "AA:00", "name": "Phone", "connected": False, "paired": True},
    {"mac": "BB:00", "name": "DashKit", "connected": True, "paired": True},
  ])
  assert st == {"connected": True, "name": "DashKit"}


def test_from_devices_empty():
  assert radio_status.from_devices([]) == {"connected": False, "name": ""}


def test_write_only_on_change(tmp_path):
  path = tmp_path / "radio.json"
  devices = [{"mac": "AA:00", "name": "Phone", "connected": True, "paired": True}]
  radio_status.write(devices, path)
  first = path.read_bytes()
  mtime = path.stat().st_mtime_ns
  radio_status.write(devices, path)
  assert path.read_bytes() == first and path.stat().st_mtime_ns == mtime
  st = radio_status.read(path)
  assert st["connected"] and st["name"] == "Phone"


def test_off_reason(tmp_path):
  from openpilot.system.dpbridge.radio_status import off_reason
  p = tmp_path / "bt_reason"
  assert off_reason(str(p)) == ""
  p.write_text("off: did not start twice\n")
  assert off_reason(str(p)) == "off: did not start twice"
  p.write_bytes(b"\xff\xfe garbage")
  assert off_reason(str(p)) == ""  # never crashes the UI
  p.write_text("")
  assert off_reason(str(p)) == ""
