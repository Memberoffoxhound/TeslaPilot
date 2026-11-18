import random

from openpilot.system.dpbridge.dkwire import frames, pack

FS = [(123456, 0, 0x257, bytes(8)), (123999, 1, 0x249, b'\x01\x02\x03'), (0xFFFFFFFF, 1, 0x3E9, bytes(range(8))), (5, 0, 0x118, b'')]


def test_roundtrip():
  assert frames(pack(FS)) == FS


def test_rejects_malformed():
  b = pack(FS)
  assert frames(b'') is None
  assert frames(b'\x00') is None
  assert frames(b[:-1]) is None
  assert frames(b + b'\x00') is None
  assert frames(bytes([len(FS) + 1]) + b[1:]) is None
  assert frames(pack([(1, 0, 1, b'')])[:-1] + b'\x09' + bytes(9)) is None  # len > 8


def test_fuzz_never_raises():
  rng = random.Random(0)
  for _ in range(5000):
    b = rng.randbytes(rng.randrange(0, 64))
    r = frames(b)
    assert r is None or pack(r) == b
