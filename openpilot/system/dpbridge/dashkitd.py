#!/usr/bin/env python3
import sys
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


def probe(link, seconds=5.0, need=10, mono=time.monotonic) -> bool:
  # one-shot check for test_bt.sh; run with DashKitBridge off, DashKit serves one link at a time
  ver = link.open()
  link.ping()
  n, end = 0, mono() + seconds
  while mono() < end:
    b = link.recv(0.5)
    n += bool(b and frames(b))
  print(f"DashKit {ver or '?'}: {n} valid packets in {seconds:.0f} s")
  return ver.startswith('0.3') and n >= need


def main():
  from jeepney.io.blocking import open_dbus_connection
  import openpilot.cereal.messaging as messaging
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog

  params = Params()
  mac = params.get("DashKitAddr")
  if not mac:
    sys.exit("no DashKitAddr, pair DashKit in settings first")
  if '--probe' in sys.argv:
    link = BleLink(Bluez(open_dbus_connection(bus='SYSTEM')), mac)
    try:
      sys.exit(0 if probe(link) else 1)
    finally:
      link.close()
  pm = messaging.PubMaster(['customReservedRawData0'])
  backoff = 2
  while True:
    # a fresh D-Bus connection each round, so a bluetoothd restart can't wedge us
    conn = link = None
    try:
      conn = open_dbus_connection(bus='SYSTEM')
      link = BleLink(Bluez(conn), mac)
      params.put("DashKitVersion", link.open())
      backoff = 2
      stream(link, lambda b: pm.send('customReservedRawData0', messaging.new_message(None, customReservedRawData0=b)))
    except Exception:
      cloudlog.exception("dashkitd: link failed")
    finally:
      if link is not None:
        link.close()
      if conn is not None:
        conn.close()
    time.sleep(backoff)
    backoff = min(backoff * 2, 30)

if __name__ == "__main__":
  main()
