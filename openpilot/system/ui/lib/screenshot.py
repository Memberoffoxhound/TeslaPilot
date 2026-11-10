"""3s display hold → PNG in /data/media/0/screenshots. Web UI sets SHOT_REQ."""
import os
import struct
import time
import zlib

import numpy as np
import raylib_nb as rl

from openpilot.common.swaglog import cloudlog

SHOT_DIR = "/data/media/0/screenshots"
SHOT_PLAY = "/data/screenshot_play"
SHOT_REQ = "/data/screenshot_request"
HOLD_S = 3.0
MOVE_PX = 28


class ScreenShotter:
  def __init__(self):
    self._t: float | None = None
    self._pos: tuple[float, float] | None = None
    self._fired = False
    self.pending = False
    self.flash = 0.0

  def _arm(self) -> None:
    self._fired = True
    self._t = None
    self.pending = True
    try:
      with open(SHOT_PLAY, "w") as f:
        f.write("1")
    except OSError:
      pass

  def held(self, events) -> bool:
    try:
      if os.path.isfile(SHOT_REQ):
        os.remove(SHOT_REQ)
        self._arm()
        return True
    except OSError:
      pass
    for e in events:
      if e.left_pressed:
        self._t = time.monotonic()
        self._pos = (e.pos.x, e.pos.y)
        self._fired = False
      if e.left_down and self._pos is not None:
        if abs(e.pos.x - self._pos[0]) > MOVE_PX or abs(e.pos.y - self._pos[1]) > MOVE_PX:
          self._t = None
      if e.left_released:
        self._t = None
    if self._t is not None and not self._fired and (time.monotonic() - self._t) >= HOLD_S:
      self._arm()
      return True
    return False

  def capture(self, render_texture=None) -> str | None:
    self.pending = False
    try:
      if render_texture is None:
        raise RuntimeError("no capture texture")
      img = rl.load_image_from_texture(render_texture.texture)
      try:
        w, h = img.width, img.height
        rgba = np.frombuffer(img.to_bytes(w * h * 4), dtype=np.uint8).reshape(h, w, 4)
      finally:
        rl.unload_image(img)
      os.makedirs(SHOT_DIR, exist_ok=True)
      path = os.path.join(SHOT_DIR, time.strftime("%Y-%m-%d--%H-%M-%S.png"))
      write_png(path, rgba[::-1])  # texture readback is upside down
      self.flash = 1.0
      return path
    except Exception:
      cloudlog.exception("screenshot failed")
      return None

  def draw_flash(self, width: int, height: int, dt: float) -> None:
    if self.flash <= 0:
      return
    a = int(255 * self.flash)
    rl.draw_rectangle(0, 0, width, height, rl.Color(255, 255, 255, a))
    self.flash = max(0.0, self.flash - dt / 0.22)


def png_bytes(rgba: np.ndarray) -> bytes:
  """Encode an HxWx4 uint8 array as RGBA PNG."""
  h, w = rgba.shape[:2]
  raw = np.zeros((h, w * 4 + 1), dtype=np.uint8)  # filter byte 0 per row
  raw[:, 1:] = np.ascontiguousarray(rgba, dtype=np.uint8).reshape(h, w * 4)

  def chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

  ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
  return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6)) + chunk(b"IEND", b"")


def write_png(path: str, rgba: np.ndarray) -> None:
  tmp = path + ".tmp"
  with open(tmp, "wb") as f:
    f.write(png_bytes(rgba))
  os.replace(tmp, path)
