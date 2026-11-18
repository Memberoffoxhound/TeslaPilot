import os

from jeepney import DBusAddress, MatchRule, Properties, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.wrappers import unwrap_msg

BLUEZ = 'org.bluez'
ADAPTER = '/org/bluez/hci0'
ADAPTER_IF = 'org.bluez.Adapter1'
DEVICE_IF = 'org.bluez.Device1'
CHAR_IF = 'org.bluez.GattCharacteristic1'

DASHKIT_NAME = 'DashKit'
UUID_CAN = 'cada0001-ca00-b1e0-b0d6-c000aa0100a1'
UUID_CONTROL = 'cada0004-ca00-b1e0-b0d6-c000aa0100a1'
UUID_VERSION = 'cada0005-ca00-b1e0-b0d6-c000aa0100a1'
PING = bytes([0x45, 0x01])  # DashKit keepalive, drops the link after 60 s without one


def hci_present() -> bool:
  return os.path.exists('/sys/class/bluetooth/hci0')


def dev_path(mac: str) -> str:
  return f"{ADAPTER}/dev_{mac.upper().replace(':', '_')}"


def props_changed(path: str) -> MatchRule:
  return MatchRule(type='signal', sender=BLUEZ, interface='org.freedesktop.DBus.Properties', member='PropertiesChanged', path=path)


class Bluez:
  def __init__(self, conn):
    self.conn = conn

  def call(self, path, iface, method, sig=None, body=(), timeout=30):
    return unwrap_msg(self.conn.send_and_get_reply(new_method_call(DBusAddress(path, BLUEZ, iface), method, sig, body), timeout=timeout))

  def get(self, path, iface, prop):
    return unwrap_msg(self.conn.send_and_get_reply(Properties(DBusAddress(path, BLUEZ, iface)).get(prop)))[0][1]

  def set(self, path, iface, prop, sig, value):
    unwrap_msg(self.conn.send_and_get_reply(Properties(DBusAddress(path, BLUEZ, iface)).set(prop, sig, value)))

  def watch(self, rule: MatchRule):
    unwrap_msg(self.conn.send_and_get_reply(message_bus.AddMatch(rule)))
    return self.conn.filter(rule, bufsize=256)

  def objects(self) -> dict:
    return self.call('/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects')[0]

  def devices(self) -> list[dict]:
    out = []
    for path, ifs in self.objects().items():
      d = ifs.get(DEVICE_IF)
      if d is not None and path.startswith(ADAPTER + '/'):
        v = {k: x[1] for k, x in d.items()}
        out.append({'mac': v['Address'], 'name': v.get('Name', ''), 'rssi': v.get('RSSI'), 'paired': v.get('Paired', False),
                    'connected': v.get('Connected', False), 'dashkit': v.get('Name') == DASHKIT_NAME})
    return out

  def char(self, dev: str, uuid: str) -> str | None:
    for path, ifs in self.objects().items():
      c = ifs.get(CHAR_IF)
      if c is not None and path.startswith(dev + '/') and c['UUID'][1].lower() == uuid:
        return path
    return None
