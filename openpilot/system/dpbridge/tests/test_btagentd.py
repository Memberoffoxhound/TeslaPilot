from itertools import count

from jeepney import DBusAddress, HeaderFields, MessageType, new_error, new_method_call, new_method_return

from openpilot.system.dpbridge import btagentd
from openpilot.system.dpbridge.bluez import dev_path

MAC = 'AA:BB:CC:DD:EE:01'


class FakeConn:
  def __init__(self):
    self.outgoing_serial = count(100)
    self.sent = []

  def send(self, msg, serial=None):
    self.sent.append((serial, msg))


class FakeBz:
  def __init__(self, name='DashKit', paired=True):
    self.conn, self.calls, self.props = FakeConn(), [], {'Name': name, 'Paired': paired, 'Discoverable': False}

  def call(self, path, iface, method, sig=None, body=(), timeout=30):
    self.calls.append((path, method, body))

  def get(self, path, iface, prop):
    return self.props[prop]

  def set(self, path, iface, prop, sig, value):
    self.calls.append((path, f'set {prop}', value))

  def devices(self):
    return []


class FakeParams(dict):
  def get(self, k):
    return super().get(k)

  def put(self, k, v):
    self[k] = v

  def remove(self, k):
    self.pop(k, None)


def agent_call(member, sig, body):
  msg = new_method_call(DBusAddress(btagentd.AGENT_PATH, 'org.bluez', 'org.bluez.Agent1'), member, sig, body)
  msg.header.serial = 7
  return msg


def reply_kind(msg):
  return msg.header.message_type


def setup(**kw):
  bz, params = FakeBz(**kw), FakeParams()
  return btagentd.Pairing(bz, params), bz, params


def pair(p, bz, ok=True):
  p.command(f'pair:{MAC}', 0)
  serial, call = bz.conn.sent[-1]
  reply = new_method_return(call) if ok else new_error(call, 'org.bluez.Error.AuthenticationFailed')
  reply.header.fields[HeaderFields.reply_serial] = serial
  return reply


def test_pairing_dashkit_saves_address_and_trusts():
  p, bz, params = setup()
  reply = pair(p, bz)
  assert p.status(0)['pairing'] == [MAC]
  p.message(reply)
  assert params['DashKitAddr'] == MAC
  assert (dev_path(MAC), 'set Trusted', True) in bz.calls
  assert p.status(0)['pairing'] == []


def test_pairing_a_phone_does_not_touch_dashkit_address():
  p, bz, params = setup(name='iPhone')
  p.message(pair(p, bz))
  assert 'DashKitAddr' not in params


def test_failed_pairing_reports_error():
  p, bz, params = setup()
  p.message(pair(p, bz, ok=False))
  assert 'AuthenticationFailed' in p.error and 'DashKitAddr' not in params


def test_just_works_only_for_our_pairing():
  p, bz, _ = setup()
  p.message(agent_call('RequestAuthorization', 'o', (dev_path(MAC),)))
  assert reply_kind(bz.conn.sent[-1][1]) == MessageType.error
  pair(p, bz)
  p.message(agent_call('RequestAuthorization', 'o', (dev_path(MAC),)))
  assert reply_kind(bz.conn.sent[-1][1]) == MessageType.method_return


def test_phone_code_waits_for_user():
  p, bz, _ = setup()
  p.message(agent_call('RequestConfirmation', 'ou', (dev_path(MAC), 4821)))
  assert p.status(0)['passkey'] == '004821' and not bz.conn.sent
  p.command('confirm:1', 0)
  assert reply_kind(bz.conn.sent[-1][1]) == MessageType.method_return and p.passkey == ''
  p.message(agent_call('RequestConfirmation', 'ou', (dev_path(MAC), 1)))
  p.command('confirm:0', 0)
  assert reply_kind(bz.conn.sent[-1][1]) == MessageType.error


def test_service_needs_a_bond_and_pin_entry_is_refused():
  p, bz, _ = setup(paired=False)
  p.message(agent_call('AuthorizeService', 'os', (dev_path(MAC), '0000110b-0000-1000-8000-00805f9b34fb')))
  assert reply_kind(bz.conn.sent[-1][1]) == MessageType.error
  p.message(agent_call('RequestPinCode', 'o', (dev_path(MAC),)))
  assert reply_kind(bz.conn.sent[-1][1]) == MessageType.error


def test_forget_clears_dashkit():
  p, bz, params = setup()
  params.update(DashKitAddr=MAC, DashKitVersion='0.3.2')
  p.command(f'forget:{MAC}', 0)
  assert ('/org/bluez/hci0', 'RemoveDevice', (dev_path(MAC),)) in bz.calls
  assert 'DashKitAddr' not in params and 'DashKitVersion' not in params


def test_scan_stops_after_window():
  p, bz, _ = setup()
  p.command('scan', 0)
  assert p.status(5)['scanning']
  p.tick(5)
  assert bz.calls[-1][1] == 'StartDiscovery'
  p.tick(btagentd.SCAN_S + 1)
  assert bz.calls[-1][1] == 'StopDiscovery' and not p.status(btagentd.SCAN_S + 1)['scanning']


def test_main_survives_bluetoothd_not_ready(monkeypatch):
  import sys
  from types import SimpleNamespace
  monkeypatch.setitem(sys.modules, 'openpilot.common.params', SimpleNamespace(Params=FakeParams))
  monkeypatch.setitem(sys.modules, 'openpilot.common.swaglog', SimpleNamespace(cloudlog=SimpleNamespace(exception=lambda *a: None)))
  attempts = []

  def connect(bus):
    attempts.append(bus)
    if len(attempts) < 3:
      raise ConnectionRefusedError  # no system bus or bluetoothd yet
    conn = FakeConn()
    conn.filter = lambda *a, **kw: SimpleNamespace(__enter__=lambda: None)
    conn.close = lambda: None
    return conn

  class Stop(Exception):
    pass

  def sleep(s):
    if len(attempts) >= 4:
      raise Stop

  monkeypatch.setattr(btagentd, 'open_dbus_connection', connect)
  monkeypatch.setattr(btagentd.time, 'sleep', sleep)
  monkeypatch.setattr(btagentd, 'Bluez', lambda conn: (_ for _ in ()).throw(RuntimeError('org.bluez not on the bus')))
  try:
    btagentd.main()
  except Stop:
    pass
  assert len(attempts) == 4  # kept retrying instead of exiting


def test_status_written_only_on_change_and_while_watched():
  p, bz, params = setup()
  p.publish(1.0)
  assert 'DpbStatus' not in params  # page closed: no flash writes
  p.command('status', 1.0)
  p.publish(1.0)
  first = params.pop('DpbStatus')
  p.publish(2.0)
  assert 'DpbStatus' not in params  # unchanged
  bz.props['Discoverable'] = True
  p.publish(3.0)
  assert params.pop('DpbStatus')['discoverable']
  bz.props['Discoverable'] = False
  p.publish(1.0 + btagentd.WATCH_S + 1)
  assert 'DpbStatus' not in params and first  # page gone quiet: stop


def test_phone_code_is_published_without_the_page():
  p, bz, params = setup()
  p.agent(agent_call('RequestConfirmation', 'ou', (dev_path(MAC), 42)))
  p.publish(100.0)
  assert params['DpbStatus']['passkey'] == '000042'


def test_discoverable_also_limits_pairable():
  p, bz, params = setup()
  p.command('discoverable', 0)
  assert ('/org/bluez/hci0', 'set PairableTimeout', btagentd.DISCOVERABLE_S) in bz.calls
