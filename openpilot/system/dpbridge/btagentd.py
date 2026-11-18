#!/usr/bin/env python3
import time
from collections import deque

from jeepney import DBusAddress, HeaderFields, MatchRule, MessageType, new_error, new_method_call, new_method_return
from jeepney.io.blocking import open_dbus_connection

from openpilot.system.dpbridge.bluez import ADAPTER, ADAPTER_IF, BLUEZ, DASHKIT_NAME, DEVICE_IF, Bluez, dev_path

# Owns pairing for the settings page: scan, pair, forget, discoverable, and the agent that shows a phone's code.
# UI -> DpbCmd ("scan", "pair:<mac>", "forget:<mac>", "discoverable", "confirm:1|0"); status -> DpbStatus.
AGENT_PATH = '/dpbridge/agent'
SCAN_S = 10
DISCOVERABLE_S = 120
STATUS_S = 0.5
RETRY_S = 5
REJECTED = 'org.bluez.Error.Rejected'


def mac_of(path: str) -> str:
  return path.rsplit('/dev_', 1)[-1].replace('_', ':')


class Pairing:
  def __init__(self, bz: Bluez, params):
    self.bz, self.params = bz, params
    self.scan_until = 0.0
    self.pending: dict[int, str] = {}  # serial of an in-flight Pair() -> mac
    self.confirm = None  # RequestConfirmation waiting for the user
    self.passkey = ''
    self.error = ''

  def command(self, cmd: str, now: float):
    verb, _, arg = cmd.partition(':')
    self.error = ''
    if verb == 'scan':
      self.bz.call(ADAPTER, ADAPTER_IF, 'StartDiscovery')
      self.scan_until = now + SCAN_S
    elif verb == 'pair':
      serial = next(self.bz.conn.outgoing_serial)
      self.bz.conn.send(new_method_call(DBusAddress(dev_path(arg), BLUEZ, DEVICE_IF), 'Pair'), serial=serial)
      self.pending[serial] = arg
    elif verb == 'forget':
      self.bz.call(ADAPTER, ADAPTER_IF, 'RemoveDevice', 'o', (dev_path(arg),))
      if self.params.get("DashKitAddr") == arg:
        self.params.remove("DashKitAddr")
        self.params.remove("DashKitVersion")
    elif verb == 'discoverable':
      self.bz.set(ADAPTER, ADAPTER_IF, 'Pairable', 'b', True)
      self.bz.set(ADAPTER, ADAPTER_IF, 'DiscoverableTimeout', 'u', DISCOVERABLE_S)
      self.bz.set(ADAPTER, ADAPTER_IF, 'Discoverable', 'b', True)
    elif verb == 'confirm' and self.confirm is not None:
      ok = arg == '1'
      self.bz.conn.send(new_method_return(self.confirm) if ok else new_error(self.confirm, REJECTED))
      self.confirm, self.passkey = None, ''

  def message(self, msg):
    h = msg.header
    if h.message_type == MessageType.method_call:
      self.agent(msg)
    elif h.fields.get(HeaderFields.reply_serial) in self.pending:
      mac = self.pending.pop(h.fields[HeaderFields.reply_serial])
      if h.message_type == MessageType.error:
        self.error = f"pairing failed: {h.fields.get(HeaderFields.error_name, '')}"
      else:
        self.paired(mac)

  def paired(self, mac: str):
    path = dev_path(mac)
    self.bz.set(path, DEVICE_IF, 'Trusted', 'b', True)
    if self.bz.get(path, DEVICE_IF, 'Name') == DASHKIT_NAME:
      self.params.put("DashKitAddr", mac)

  def agent(self, msg):
    member, body = msg.header.fields.get(HeaderFields.member), msg.body
    reply = new_method_return(msg)
    if member == 'RequestConfirmation':
      self.confirm, self.passkey = msg, f'{body[1]:06d}'
      return
    if member == 'RequestAuthorization':
      # Just Works: only for a pairing we started from the settings page
      if mac_of(body[0]) not in self.pending.values():
        reply = new_error(msg, REJECTED)
    elif member == 'AuthorizeService':
      if not self.bz.get(body[0], DEVICE_IF, 'Paired'):
        reply = new_error(msg, REJECTED)
    elif member == 'Cancel':
      self.confirm, self.passkey = None, ''
    elif member != 'Release':
      reply = new_error(msg, REJECTED)  # no PIN or passkey entry on this device
    self.bz.conn.send(reply)

  def tick(self, now: float):
    if self.scan_until and now > self.scan_until:
      self.scan_until = 0.0
      self.bz.call(ADAPTER, ADAPTER_IF, 'StopDiscovery')

  def status(self, now: float) -> dict:
    return {'devices': self.bz.devices(), 'scanning': now < self.scan_until, 'pairing': sorted(self.pending.values()),
            'discoverable': bool(self.bz.get(ADAPTER, ADAPTER_IF, 'Discoverable')), 'passkey': self.passkey, 'error': self.error}


def serve(params, conn, log):
  bz = Bluez(conn)
  p = Pairing(bz, params)

  # agent calls and Pair() replies can arrive while another call waits; filters keep them
  inbox: deque = deque(maxlen=64)
  for t in ('method_call', 'method_return', 'error'):
    conn.filter(MatchRule(type=t), queue=inbox).__enter__()

  bz.set(ADAPTER, ADAPTER_IF, 'Powered', 'b', True)
  bz.call('/org/bluez', 'org.bluez.AgentManager1', 'RegisterAgent', 'os', (AGENT_PATH, 'DisplayYesNo'))
  bz.call('/org/bluez', 'org.bluez.AgentManager1', 'RequestDefaultAgent', 'o', (AGENT_PATH,))

  last_status = 0.0
  while True:
    now = time.monotonic()
    cmd = params.get("DpbCmd")
    if cmd:
      params.remove("DpbCmd")
      try:
        p.command(cmd, now)
      except Exception as e:
        log("btagentd: command failed")
        p.error = str(e)
    p.tick(now)
    try:
      conn.recv_messages(timeout=0.1)
    except TimeoutError:
      pass
    while inbox:
      p.message(inbox.popleft())
    if now - last_status > STATUS_S:
      params.put("DpbStatus", p.status(now))
      last_status = now


def main():
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog

  params = Params()
  while True:
    # bluetoothd may not be up yet, or may restart: start over instead of exiting
    conn = None
    try:
      conn = open_dbus_connection(bus='SYSTEM')
      serve(params, conn, cloudlog.exception)
    except Exception:
      cloudlog.exception("btagentd: restarting")
    finally:
      if conn is not None:
        conn.close()
    time.sleep(RETRY_S)


if __name__ == "__main__":
  main()
