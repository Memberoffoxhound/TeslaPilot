from openpilot.system.dpbridge.a2dp import DUCK, FULL, MUTE, Ducker, target

PHONE = '/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_01/a2dpsnk/source'
OTHER = '/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_02/a2dpsnk/source'


class FakeBlueAlsa:
  def __init__(self, vols):
    self.vols, self.writes = dict(vols), 0

  def pcms(self):
    return list(self.vols)

  def volume(self, pcm):
    return self.vols[pcm]

  def set_volume(self, pcm, word):
    self.vols[pcm], self.writes = word, self.writes + 1


def test_target():
  assert target(onroad=False, allow_onroad=False, alert=False) == FULL
  assert target(onroad=True, allow_onroad=False, alert=False) == MUTE
  assert target(onroad=True, allow_onroad=False, alert=True) == MUTE  # an alert never unmutes music
  assert target(onroad=True, allow_onroad=True, alert=False) == FULL
  assert target(onroad=True, allow_onroad=True, alert=True) == DUCK
  assert target(onroad=False, allow_onroad=False, alert=True) == DUCK


def test_duck_and_restore_listener_volume():
  ba = FakeBlueAlsa({PHONE: 0x5050})
  d = Ducker(ba)
  d.update(DUCK)
  assert ba.vols[PHONE] == DUCK << 8 | DUCK
  d.update(MUTE)
  assert ba.vols[PHONE] == 0
  d.update(FULL)
  assert ba.vols[PHONE] == 0x5050


def test_no_writes_when_nothing_changes():
  ba = FakeBlueAlsa({PHONE: 0x5050})
  d = Ducker(ba)
  d.update(FULL)
  assert ba.writes == 0
  d.update(DUCK)
  d.update(DUCK)
  assert ba.writes == 1


def test_phone_joining_while_ducked_is_ducked_and_restored():
  ba = FakeBlueAlsa({PHONE: 0x4040})
  d = Ducker(ba)
  d.update(MUTE)
  ba.vols[OTHER] = 0x7070
  d.update(MUTE)
  assert ba.vols[OTHER] == 0
  del ba.vols[PHONE]
  d.update(FULL)
  assert ba.vols == {OTHER: 0x7070}
