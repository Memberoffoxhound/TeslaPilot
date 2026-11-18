#!/usr/bin/env python3
import subprocess
import time

# Keeps phone music out of the way: muted while driving unless DpbA2dpOnroad, down to about -20 dB during alerts.
# The mici card has one playback PCM (MultiMedia1), so soundd and bluealsa-aplay share it through dmix
# (/etc/asound.conf from install_userspace.sh). Music alone passes a softvol control; alerts never do.
# Any failure on the way down tries a full mute: music is never left loud by mistake.
CONTROL = 'dpbridge A2DP Playback Volume'
FULL, DUCK, MUTE = 100, 60, 0  # percent of the softvol range (-51 dB..0), 0 is mute


def target(onroad: bool, allow_onroad: bool, alert: bool) -> int:
  if onroad and not allow_onroad:
    return MUTE
  return DUCK if alert else FULL


def set_level(pct: int):
  subprocess.run(['amixer', '-c0', '-q', 'cset', f'name={CONTROL}', f'{pct}%'], check=True, timeout=2)


class Ducker:
  def __init__(self, set_level=set_level):
    self.set, self.level = set_level, None

  def update(self, level: int):
    if level == self.level:
      return
    self.level = None  # unknown until this update finishes
    try:
      self.set(level)
    except Exception:
      if level != FULL:
        self.set(MUTE)  # fail closed
      raise
    self.level = level


def main():
  import openpilot.cereal.messaging as messaging
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog

  params = Params()
  sm = messaging.SubMaster(['deviceState', 'selfdriveState'])
  ducker = Ducker()
  while True:
    sm.update(200)
    level = target(sm['deviceState'].started, params.get_bool("DpbA2dpOnroad"), sm['selfdriveState'].alertSound.raw != 0)
    try:
      ducker.update(level)
    except Exception:
      cloudlog.exception("dpb a2dp")
      time.sleep(1)


if __name__ == "__main__":
  main()
