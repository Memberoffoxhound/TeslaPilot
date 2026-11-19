import fcntl
import os
import struct
import termios
import time

import numpy as np

from openpilot.common.swaglog import cloudlog

FIFO = "/run/dpbridge/a2dp.fifo"  # S16_LE mono 48 kHz from bluealsa-aplay
VOL_FILE = "/data/dpbridge/music_db"  # music level in dB, e.g. -12
DEFAULT_DB = -12.0
MIN_DB = -60.0
RESUME_DELAY = 0.5  # s after an alert before music comes back
RAMP_TIME = 1.0  # s to fade back in
SAMPLE_RATE = 48000


class Music:
  def __init__(self, fifo=FIFO, vol_file=VOL_FILE):
    self.fifo, self.vol_file = fifo, vol_file
    self.fd = None
    self.buf = b""
    self.db = DEFAULT_DB
    self.fade = 0.
    self.quiet_until = 0.
    self.next_open = self.next_vol = self.next_warn = 0.

  def _update_db(self, now):
    if now < self.next_vol:
      return
    self.next_vol = now + 1.
    try:
      with open(self.vol_file) as f:
        self.db = float(np.clip(float(f.read().strip()), MIN_DB, 0.))
    except (OSError, ValueError):
      self.db = DEFAULT_DB

  def _open(self, now):
    if self.fd is None and now >= self.next_open:
      self.next_open = now + 1.
      try:
        self.fd = os.open(self.fifo, os.O_RDONLY | os.O_NONBLOCK)
      except OSError:
        self.fd = None

  def _read(self, frames):
    want = frames * 2
    pending = struct.unpack('i', fcntl.ioctl(self.fd, termios.FIONREAD, b'\0' * 4))[0]
    if pending + len(self.buf) > 4 * want:  # too far behind: keep the newest 2 blocks
      excess = pending + len(self.buf) - 2 * want
      excess -= excess % 2
      cut = min(excess, len(self.buf))
      self.buf, excess = self.buf[cut:], excess - cut
      while excess > 0:
        d = os.read(self.fd, min(excess, 65536))
        if not d:
          break
        excess -= len(d)
    if len(self.buf) < want:
      try:
        self.buf += os.read(self.fd, want - len(self.buf))
      except BlockingIOError:
        pass
    n = len(self.buf) // 2 * 2
    take, self.buf = self.buf[:min(n, want)], self.buf[min(n, want):]
    out = np.zeros(frames, dtype=np.float32)
    s = np.frombuffer(take, dtype=np.int16)
    out[:len(s)] = s / 32768.
    return out

  # returns the music block to add, or None when it must add nothing
  def get(self, frames, alert, now=None):
    try:
      now = time.monotonic() if now is None else now
      self._update_db(now)
      self._open(now)
      if self.fd is None:
        return None
      x = self._read(frames)
      if alert:
        self.fade, self.quiet_until = 0., now + RESUME_DELAY
        return None
      if now < self.quiet_until:
        return None
      self.fade = min(1., self.fade + frames / SAMPLE_RATE / RAMP_TIME)
      g = (10 ** (self.db / 20)) * self.fade
      return x * g if g > 0 else None
    except Exception as e:
      t = time.monotonic()
      if t >= self.next_warn:
        self.next_warn = t + 10.
        cloudlog.warning(f"dpb music: {e!r}")
      return None
