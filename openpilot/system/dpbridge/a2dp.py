#!/usr/bin/env python3
import subprocess
import time

from jeepney import DBusAddress, Properties, new_method_call

# Keeps phone music out of the way: muted while driving unless DpbA2dpOnroad, down to 10% during alerts.
# Mute cuts bluealsa's own ALSA route (MultiMedia2), so soundd and its alerts are never touched. Ducking lowers the
# A2DP PCM Volume, and any failure on the way down cuts the route: music is never left loud by mistake.
ROUTE = 'SEC_MI2S_RX Audio Mixer MultiMedia2'
BLUEALSA = 'org.bluealsa'
PCM_IF = 'org.bluealsa.PCM1'
FULL, DUCK, MUTE = 127, 13, 0  # A2DP volume is 0..127 per channel


def target(onroad: bool, allow_onroad: bool, alert: bool) -> int:
  if onroad and not allow_onroad:
    return MUTE
  return DUCK if alert else FULL


class BlueAlsa:
  def __init__(self, conn):
    self.conn = conn

  def pcms(self) -> list[str]:
    msg = new_method_call(DBusAddress('/org/bluealsa', BLUEALSA, 'org.bluealsa.Manager1'), 'GetPCMs')
    return [p for p in self.conn.send_and_get_reply(msg, timeout=2).body[0] if p.endswith('/a2dpsnk/source')]

  def volume(self, pcm: str) -> int:
    return self.conn.send_and_get_reply(Properties(DBusAddress(pcm, BLUEALSA, PCM_IF)).get('Volume'), timeout=2).body[0][1]

  def set_volume(self, pcm: str, word: int):
    self.conn.send_and_get_reply(Properties(DBusAddress(pcm, BLUEALSA, PCM_IF)).set('Volume', 'q', word), timeout=2)


def set_route(on: bool):
  subprocess.run(['amixer', '-c0', '-q', 'cset', f'name={ROUTE}', '1' if on else '0'], check=True, timeout=2)


class Ducker:
  def __init__(self, ba, route=set_route):
    self.ba, self.route, self.level, self.pcms = ba, route, None, set()
    self.saved: dict[str, int] = {}  # the listener's own volume while we hold it down

  def update(self, level: int):
    try:
      pcms = set(self.ba.pcms())
      if level == self.level and pcms == self.pcms:
        return
      self.level = None  # unknown until this update finishes
      if level == DUCK:
        for pcm in pcms:
          self.saved.setdefault(pcm, self.ba.volume(pcm))
          self.ba.set_volume(pcm, level << 8 | level)
      elif level == FULL:
        self.restore(pcms)
      self.route(level != MUTE)
    except Exception:
      if level != FULL:
        self.route(False)  # fail closed
      raise
    self.saved = {p: v for p, v in self.saved.items() if p in pcms}
    self.level, self.pcms = level, pcms

  def restore(self, pcms):
    for pcm in pcms & self.saved.keys():
      self.ba.set_volume(pcm, self.saved[pcm])
    self.saved = {}


def main():
  from jeepney.io.blocking import open_dbus_connection
  import openpilot.cereal.messaging as messaging
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog

  params = Params()
  sm = messaging.SubMaster(['deviceState', 'selfdriveState'])
  ducker = Ducker(BlueAlsa(open_dbus_connection(bus='SYSTEM')))
  try:
    while True:
      sm.update(200)
      level = target(sm['deviceState'].started, params.get_bool("DpbA2dpOnroad"), sm['selfdriveState'].alertSound.raw != 0)
      try:
        ducker.update(level)
      except Exception:
        cloudlog.exception("dpb a2dp")  # bluealsa not up yet or a PCM vanished; retry next tick
        time.sleep(1)
  finally:
    ducker.restore(set(ducker.ba.pcms()))  # the route stays as it was, so a crash onroad leaves music muted


if __name__ == "__main__":
  main()
