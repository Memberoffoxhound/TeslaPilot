from openpilot.system.hardware.accel_detect import AccelDetect, GRACE_S, PROBE_S, ABSENT_S


class FakeParams(dict):
  def get(self, key):
    return super().get(key)

  def put(self, key, value):
    self[key] = value

  def get_bool(self, key):
    return bool(super().get(key, False))


class Rig:
  def __init__(self, device='none', **params):
    self.t, self.chestnut, self.cable, self.present = 100.0, False, False, False
    self.p = FakeParams(AcceleratorDevice=device, JetlinkLink=0, **params)
    self.d = AccelDetect(self.p, now=lambda: self.t, chestnut=lambda: self.chestnut,
                         cable=lambda: self.cable, present=lambda: self.present)

  def run(self, seconds, onroad=False):
    for _ in range(int(seconds / 0.5)):
      self.t += 0.5
      self.d.step(onroad)

  @property
  def link(self):
    return self.p['JetlinkLink']

  @property
  def device(self):
    return self.p['AcceleratorDevice']


def test_boot_starts_in_remembered_mode():
  assert Rig('jetlink-usb').link == 1
  assert Rig('jetlink-ios').link == 2
  assert Rig('chestnut').link == 0


def test_probe_finds_jetson():
  r = Rig()
  r.cable = True
  r.run(GRACE_S + 0.5)
  assert r.link == 1
  r.present = True
  r.run(1)
  assert r.device == 'jetlink-usb' and r.link == 1


def test_probe_gives_up_once_per_plug():
  r = Rig()
  r.cable = True
  r.run(GRACE_S + PROBE_S + 1)
  assert r.link == 0 and r.device == 'none'
  r.run(30)
  assert r.link == 0
  r.cable = False
  r.run(1)
  r.cable = True
  r.run(GRACE_S + 0.5)
  assert r.link == 1


def test_chestnut_wins():
  r = Rig('jetlink-usb')
  r.cable = r.chestnut = True
  r.run(1)
  assert r.device == 'chestnut' and r.link == 0


def test_adb_blocks_jetlink():
  r = Rig('jetlink-usb', AdbEnabled=True)
  r.cable = True
  r.run(GRACE_S + PROBE_S + 1)
  assert r.link == 0 and r.device == 'jetlink-usb'
  r.p['AdbEnabled'] = False
  r.run(1)
  assert r.link == 1


def test_ios_is_manual():
  r = Rig(JetlinkIos=True)
  r.run(1)
  assert r.device == 'jetlink-ios' and r.link == 2
  r.p['JetlinkIos'] = False
  r.run(1)
  assert r.device == 'none' and r.link == 0


def test_onroad_writes_nothing():
  r = Rig()
  r.cable = r.chestnut = True
  r.run(5, onroad=True)
  assert r.device == 'none'


def test_missing_jetson_forgotten_only_with_a_host():
  r = Rig('jetlink-usb')
  r.run(ABSENT_S * 2)
  assert r.device == 'jetlink-usb'
  r.cable = True
  r.run(ABSENT_S + 1)
  assert r.device == 'none' and r.link == 0


def test_chestnut_memory_probes_a_host():
  r = Rig('chestnut')
  r.cable = True
  r.run(GRACE_S + 0.5)
  r.present = True
  r.run(1)
  assert r.device == 'jetlink-usb'


def test_unplugged_link_is_off_memory_stays():
  r = Rig('jetlink-usb')
  assert r.link == 1
  r.run(1)
  assert r.device == 'jetlink-usb' and r.link == 0
  r.cable = True
  r.run(0.5)
  assert r.link == 1

