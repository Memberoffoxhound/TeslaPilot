import struct

# DashKit BLE notify payload: [count], then per frame [ts_us u32][bus u8][addr u32][len u8][data, len <= 8]
HDR = struct.Struct('<IBIB')


def frames(b: bytes) -> list[tuple[int, int, int, bytes]] | None:
  # parsed frames, or None if the payload is malformed or empty
  if not b or not b[0]:
    return None
  out, i = [], 1
  for _ in range(b[0]):
    if i + HDR.size > len(b):
      return None
    ts, bus, addr, n = HDR.unpack_from(b, i)
    i += HDR.size
    if n > 8 or i + n > len(b):
      return None
    out.append((ts, bus, addr, bytes(b[i:i + n])))
    i += n
  return out if i == len(b) else None


def pack(fs: list[tuple[int, int, int, bytes]]) -> bytes:
  return bytes([len(fs)]) + b''.join(HDR.pack(ts, bus, addr, len(d)) + d for ts, bus, addr, d in fs)
