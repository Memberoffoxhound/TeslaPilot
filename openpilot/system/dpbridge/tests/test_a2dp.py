import pytest

from openpilot.system.dpbridge.a2dp import DUCK, FULL, MUTE, Ducker, target


class Mixer(list):
  def __init__(self, broken=()):
    super().__init__()
    self.broken = set(broken)

  def __call__(self, pct):
    if pct in self.broken:
      raise TimeoutError
    self.append(pct)


def test_target():
  assert target(onroad=False, allow_onroad=False, alert=False) == FULL
  assert target(onroad=True, allow_onroad=False, alert=False) == MUTE
  assert target(onroad=True, allow_onroad=False, alert=True) == MUTE  # an alert never unmutes music
  assert target(onroad=True, allow_onroad=True, alert=False) == FULL
  assert target(onroad=True, allow_onroad=True, alert=True) == DUCK
  assert target(onroad=False, allow_onroad=False, alert=True) == DUCK


def test_levels_and_no_repeat_writes():
  m = Mixer()
  d = Ducker(m)
  for level in (FULL, FULL, DUCK, DUCK, MUTE, FULL):
    d.update(level)
  assert m == [FULL, DUCK, MUTE, FULL]


def test_duck_failure_mutes():
  m = Mixer(broken={DUCK})
  d = Ducker(m)
  d.update(FULL)
  with pytest.raises(TimeoutError):
    d.update(DUCK)
  assert m[-1] == MUTE and d.level is None
  m.broken.clear()
  d.update(DUCK)  # retried next tick
  assert m[-1] == DUCK


def test_full_failure_does_not_mute():
  m = Mixer(broken={FULL})
  d = Ducker(m)
  with pytest.raises(TimeoutError):
    d.update(FULL)
  assert m == []
