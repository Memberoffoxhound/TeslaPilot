import ast
import struct
import zlib
from pathlib import Path

import numpy as np
import raylib_nb as rl

from openpilot.system.ui.lib.screenshot import png_bytes

LIB = Path(__file__).parents[1]
CAPTURE_FILES = ["application.py", "screenshot.py"]


def _rl_calls(path: Path) -> set[str]:
  tree = ast.parse(path.read_text())
  return {n.attr for n in ast.walk(tree)
          if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "rl"}


def test_capture_uses_only_bound_raylib():
  # catches binding swaps that drop functions we call
  patched = {"_orig_draw_text_ex", "_orig_begin_scissor_mode"}
  for f in CAPTURE_FILES:
    missing = sorted(n for n in _rl_calls(LIB / f) - patched if not hasattr(rl, n))
    assert not missing, f"{f}: raylib_nb lacks {missing}"


def _decode_png(data: bytes) -> np.ndarray:
  assert data[:8] == b"\x89PNG\r\n\x1a\n"
  pos, idat, ihdr = 8, b"", None
  while pos < len(data):
    (n,) = struct.unpack(">I", data[pos:pos + 4])
    tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
    (crc,) = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])
    assert crc == zlib.crc32(tag + body)
    if tag == b"IHDR":
      ihdr = struct.unpack(">IIBBBBB", body)
    elif tag == b"IDAT":
      idat += body
    pos += 12 + n
  w, h, depth, ctype = ihdr[:4]
  assert (depth, ctype) == (8, 6)
  raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, w * 4 + 1)
  assert not raw[:, 0].any()
  return raw[:, 1:].reshape(h, w, 4)


def test_png_round_trip_and_flip():
  img = np.random.default_rng(0).integers(0, 256, (5, 7, 4), dtype=np.uint8)
  assert np.array_equal(_decode_png(png_bytes(img)), img)
  flipped = _decode_png(png_bytes(img[::-1]))
  assert np.array_equal(flipped[0], img[-1])


def test_capture_flips_cpu_screen(tmp_path, monkeypatch):
  from openpilot.system.ui.lib import screenshot
  monkeypatch.setattr(screenshot, "SHOT_DIR", str(tmp_path))
  screen = np.random.default_rng(1).integers(0, 256, (4, 6, 4), dtype=np.uint8)
  path = screenshot.ScreenShotter().capture(screen)
  assert np.array_equal(_decode_png(Path(path).read_bytes()), screen[::-1])
