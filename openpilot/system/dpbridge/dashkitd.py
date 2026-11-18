#!/usr/bin/env python3
import time
from contextlib import ExitStack

from openpilot.system.dpbridge.bluez import CHAR_IF, DEVICE_IF, PING, UUID_CAN, UUID_CONTROL, UUID_VERSION, Bluez, dev_path, props_changed
from openpilot.system.dpbridge.dkwire import frames

# Log only: DashKit payloads go verbatim into customReservedRawData0 (rlog) and nowhere else.
PING_S = 15
STALE_S = 10  # DashKit streams nonstop onroad, so this much silence means the link is gone


class BleLink:
  def __init__(self, bz: Bluez, mac: str):
    self.bz, self.dev = bz, dev_path(mac)
    self.stack = ExitStack()
    self.can = self.ctrl = self.q = None

  def open(self) -> str:
    bz = self.bz
    bz.call(self.dev, DEVICE_IF, 'Connect')
    for _ in range(50):
      if bz.get(self.dev, DEVICE_IF, 'ServicesResolved'):
        break
      time.sleep(0.1)
    self.can, self.ctrl, ver = (bz.char(self.dev, u) for u in (UUID_CAN, UUID_CONTROL, UUID_VERSION))
    if not (self.can and self.ctrl):
      raise RuntimeError('DashKit GATT service not found')
    self.q = self.stack.enter_context(bz.watch(props_changed(self.can)))
    # taking the stream makes us DashKit's active link; the phone loses it until we let go
    bz.call(self.can, CHAR_IF, 'StartNotify')
    return bytes(bz.call(ver, CHAR_IF, 'ReadValue', 'a{sv}', ({},))[0]).decode(errors='replace') if ver else ''

  def ping(self):
    self.bz.call(self.ctrl, CHAR_IF, 'WriteValue', 'aya{sv}', (PING, {'type': ('s', 'request')}))

  def recv(self, timeout: float) -> bytes | None:
    try:
      msg = self.bz.conn.recv_until_filtered(self.q, timeout=timeout)
    except TimeoutError:
      return None
    value = msg.body[1].get('Value')
    return bytes(value[1]) if value else None

  def close(self):
    for path, iface, method in ((self.can, CHAR_IF, 'StopNotify'), (self.dev, DEVICE_IF, 'Disconnect')):
      if path:
        try:
          self.bz.call(path, iface, method, timeout=5)
        except Exception:
          pass
    self.stack.close()


def stream(link, publish, mono=time.monotonic):
  # returns when the link goes quiet; the caller reconnects
  last_ping = last_rx = mono()
  link.ping()
  while True:
    if mono() - last_ping >= PING_S:
      link.ping()
      last_ping = mono()
    b = link.recv(1.0)
    if b is None:
      if mono() - last_rx > STALE_S:
        return
      continue
    last_rx = mono()
    if frames(b):
      publish(b)


def main():
  from jeepney.io.blocking import open_dbus_connection
  import cereal.messaging as messaging
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog

  params = Params()
  mac = params.get("DashKitAddr")
  if not mac:
    return
  pm = messaging.PubMaster(['customReservedRawData0'])
  bz = Bluez(open_dbus_connection(bus='SYSTEM'))
  backoff = 2
  while True:
    link = BleLink(bz, mac)
    try:
      params.put("DashKitVersion", link.open())
      backoff = 2
      stream(link, lambda b: pm.send('customReservedRawData0', messaging.new_message(None, customReservedRawData0=b)))
    except Exception:
      cloudlog.exception("dashkitd: link failed")
    finally:
      link.close()
    time.sleep(backoff)
    backoff = min(backoff * 2, 30)


if __name__ == "__main__":
  main()
