# ChestnutSeen: latched once a chestnut enumerates, so the model manager fetches its model offroad
from types import SimpleNamespace

from openpilot.system.hardware.jetlink_power import JetlinkPower


class _Params:
  def __init__(self, seen=False, link=0):
    self.store = {"ChestnutSeen": seen, "JetlinkLink": link}

  def get_bool(self, key):
    return bool(self.store.get(key))

  def get(self, key, *a, **k):
    return self.store.get(key)

  def put_bool(self, key, value):
    self.store[key] = value


def _alerts(power, present):
  power.alerts(lambda *a, **k: None, SimpleNamespace(chestnutPresent=present))


def test_latches():
  params = _Params()
  power = JetlinkPower(params=params)
  _alerts(power, False)
  assert not params.store["ChestnutSeen"]
  _alerts(power, True)
  assert params.store["ChestnutSeen"] and power.chestnut_seen
  _alerts(power, False)
  assert params.store["ChestnutSeen"]


def test_written_once():
  params = _Params(seen=True)
  writes = []
  params.put_bool = lambda k, v: writes.append(k)
  power = JetlinkPower(params=params)
  _alerts(power, True)
  assert writes == []


def test_no_params_no_device_state():
  power = JetlinkPower()
  power.alerts(lambda *a, **k: None)
  _alerts(power, True)
  assert not power.chestnut_seen


def test_clears_when_jetlink_off_at_boot():
  params = _Params(seen=True, link=0)
  power = JetlinkPower(params=params)
  _alerts(power, False)
  assert not params.store["ChestnutSeen"] and not power.chestnut_seen


def test_keeps_when_jetlink_on_at_boot():
  params = _Params(seen=True, link=1)
  power = JetlinkPower(params=params)
  _alerts(power, False)
  assert params.store["ChestnutSeen"] and power.chestnut_seen


def test_keeps_when_chestnut_present_at_boot():
  params = _Params(seen=True, link=0)
  power = JetlinkPower(params=params)
  _alerts(power, True)
  assert params.store["ChestnutSeen"] and power.chestnut_seen


def test_off_path_only_at_boot():
  params = _Params(seen=False, link=0)
  power = JetlinkPower(params=params)
  _alerts(power, True)
  assert params.store["ChestnutSeen"] and power.chestnut_seen
  _alerts(power, False)
  assert params.store["ChestnutSeen"] and power.chestnut_seen
