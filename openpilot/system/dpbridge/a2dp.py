#!/usr/bin/env python3
import os
import signal
import sys
import time

# Keeps phone music out of the way: muted while driving if DpbMusicOnroad is off.
# soundd mixes A2DP from the FIFO and already mutes during alerts, so this process
# only publishes a tmpfs level that Music reads. 0 is mute. No ALSA mixer.
LEVEL_PATH = '/dev/shm/dpbridge-a2dp.level'
FULL, DUCK, MUTE = 100, 60, 0


def target(onroad: bool, allow_onroad: bool, alert: bool) -> int:
  if onroad and not allow_onroad:
    return MUTE
  return DUCK if alert else FULL


def set_level(pct: int):
  path = LEVEL_PATH
  tmp = path + '.tmp'
  with open(tmp, 'w') as f:
    f.write(str(int(pct)))
  os.replace(tmp, path)


class Ducker:
  # rewrite an unchanged level every REFRESH_S in case the reader missed a write
  REFRESH_S = 10

  def __init__(self, set_level=set_level, clock=time.monotonic):
    self.set, self.clock, self.level, self.at = set_level, clock, None, 0.0

  def update(self, level: int):
    if level == self.level and self.clock() - self.at < self.REFRESH_S:
      return
    self.level = None  # unknown until this update finishes
    try:
      self.set(level)
    except Exception:
      if level != FULL:
        self.set(MUTE)  # fail closed
      raise
    self.level, self.at = level, self.clock()


def run(ducker, levels, log, sleep=time.sleep):
  # one log line per new error and a calm retry, so a missing mixer can't flood the log or spin amixer
  err, backoff = None, 1
  try:
    for level in levels:
      try:
        ducker.update(level)
        err, backoff = None, 1
      except Exception as e:
        if repr(e) != err:
          err = repr(e)
          log(f"dpb a2dp: {err}, retrying")
        sleep(backoff)
        backoff = min(backoff * 2, 30)
  finally:
    # dying while ducked, muted or unsure: leave the music muted, not loud until the restart
    if ducker.level != FULL:
      try:
        ducker.set(MUTE)
      except Exception:
        pass


def exit_on_sigterm():
  signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so run's finally mutes on a plain kill too


def main():
  import openpilot.cereal.messaging as messaging
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog

  params = Params()
  sm = messaging.SubMaster(['deviceState', 'selfdriveState'])

  def levels():
    while True:
      sm.update(200)
      yield target(sm['deviceState'].started, params.get_bool("DpbMusicOnroad"), sm['selfdriveState'].alertSound.raw != 0)

  exit_on_sigterm()
  run(Ducker(), levels(), cloudlog.warning)


if __name__ == "__main__":
  main()
