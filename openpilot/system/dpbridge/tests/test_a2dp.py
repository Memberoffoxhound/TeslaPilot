import pytest

from openpilot.system.dpbridge.a2dp import DUCK, FULL, MUTE, Ducker, target

PHONE = '/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_01/a2dpsnk/source'
OTHER = '/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_02/a2dpsnk/source'


class FakeBlueAlsa:
  def __init__(self, vols):
    self.vols, self.writes, self.broken = dict(vols), 0, False

  def pcms(self):
    return list(self.vols)

  def volume(self, pcm):
    return self.vols[pcm]

  def set_volume(self, pcm, word):
    if self.broken:
      raise TimeoutError
    self.vols[pcm], self.writes = word, self.writes + 1


class Route(list):
  def __call__(self, on):
    self.append(on)

  @property
  def on(self):
    return self[-1] if self else None


def ducker(vols):
  ba, route = FakeBlueAlsa(vols), Route()
  return Ducker(ba, route), ba, route


def test_target():
  assert target(onroad=False, allow_onroad=False, alert=False) == FULL
  assert target(onroad=True, allow_onroad=False, alert=False) == MUTE
  assert target(onroad=True, allow_onroad=False, alert=True) == MUTE  # an alert never unmutes music
  assert target(onroad=True, allow_onroad=True, alert=False) == FULL
  assert target(onroad=True, allow_onroad=True, alert=True) == DUCK
  assert target(onroad=False, allow_onroad=False, alert=True) == DUCK


def test_duck_and_restore_listener_volume():
  d, ba, route = ducker({PHONE: 0x5050})
  d.update(DUCK)
  assert ba.vols[PHONE] == DUCK << 8 | DUCK and route.on
  d.update(MUTE)
  assert route.on is False
  d.update(FULL)
  assert ba.vols[PHONE] == 0x5050 and route.on


def test_no_writes_when_nothing_changes():
  d, ba, route = ducker({PHONE: 0x5050})
  d.update(FULL)
  assert ba.writes == 0
  d.update(DUCK)
  d.update(DUCK)
  assert ba.writes == 1 and len(route) == 2


def test_phone_joining_while_ducked_is_ducked_and_restored():
  d, ba, route = ducker({PHONE: 0x4040})
  d.update(DUCK)
  ba.vols[OTHER] = 0x7070
  d.update(DUCK)
  assert ba.vols[OTHER] == DUCK << 8 | DUCK
  del ba.vols[PHONE]
  d.update(FULL)
  assert ba.vols == {OTHER: 0x7070}


def test_mute_never_touches_the_phone_volume():
  d, ba, route = ducker({PHONE: 0x4040})
  d.update(MUTE)
  assert route.on is False and ba.writes == 0


def test_duck_failure_cuts_the_route():
  d, ba, route = ducker({PHONE: 0x5050})
  d.update(FULL)
  ba.broken = True
  with pytest.raises(TimeoutError):
    d.update(DUCK)
  assert route.on is False
  ba.broken = False
  d.update(DUCK)  # retried next tick
  assert route.on and ba.vols[PHONE] == DUCK << 8 | DUCK


def test_bluealsa_gone_still_mutes():
  d, ba, route = ducker({PHONE: 0x5050})
  ba.pcms = lambda: (_ for _ in ()).throw(ConnectionError)
  with pytest.raises(ConnectionError):
    d.update(MUTE)
  assert route.on is False
