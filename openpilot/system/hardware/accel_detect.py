# Picks the accelerator on the USB-C port and remembers it across boots (MODE_SPEC.md).
# Jetlink is switched only through JetlinkLink; jetlinkd's should_run follows it.
import time

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.modeld.accel_keys import DEVICE_KEY, known

GRACE_S = 3.0    # a chestnut enumerates within this after the cable
PROBE_S = 8.0    # how long a probe waits for a Jetlink host
ABSENT_S = 30.0  # a remembered Jetson missing this long with a host on the port is forgotten
LINK = {'none': 0, 'chestnut': 0, 'jetlink-usb': 1, 'jetlink-ios': 2}


def _chestnut() -> bool:
  from openpilot.selfdrive.modeld.helpers import chestnut_present
  return chestnut_present()


def _cable() -> bool:
  from openpilot.common.hardware.usb import cable_connected
  return cable_connected()


def _present() -> bool:
  return bool(getattr(ja.status(), 'present', False))


class AccelDetect:
  def __init__(self, params, now=time.monotonic, chestnut=_chestnut, cable=_cable, present=_present, log=None):
    self.params, self.now, self.log = params, now, log
    self.chestnut, self.cable, self.present = chestnut, cable, present
    self.device = known(params.get(DEVICE_KEY))
    self.cable_ts = self.probe_ts = self.absent_ts = None
    self.probed = False
    self._link(LINK[self.device])  # boot straight into the remembered mode

  def _link(self, value: int) -> None:
    if self.params.get(ja.KEYS.link) != value:
      self.params.put(ja.KEYS.link, value)

  def _remember(self, device: str) -> None:
    if device != self.device:
      if self.log is not None:
        self.log.warning(f"accel: {self.device} -> {device}")
      self.device = device
      self.params.put(DEVICE_KEY, device)

  def _end_probe(self) -> None:
    if self.probe_ts is not None:
      self.probe_ts = None
      self._link(LINK[self.device])

  def step(self, onroad: bool) -> None:
    if onroad:
      return
    if self.params.get_bool("AdbEnabled"):
      self.probe_ts = None
      self._link(0)
      return
    if self.chestnut():
      self.probe_ts = None
      self._remember('chestnut')
      self._link(0)
      return
    if self.params.get_bool("JetlinkIos"):
      self._remember('jetlink-ios')
      self._link(2)
      return
    if self.device == 'jetlink-ios':
      self._remember('none')

    now = self.now()
    if not self.cable():
      self.cable_ts = self.probe_ts = self.absent_ts = None
      self.probed = False
      self._link(LINK[self.device])
      return
    if self.cable_ts is None:
      self.cable_ts = now

    if self.device == 'jetlink-usb':
      self._link(1)
      if self.present():
        self.absent_ts = None
      elif self.absent_ts is None:
        self.absent_ts = now
      elif now - self.absent_ts >= ABSENT_S:
        self.absent_ts, self.probed = None, True
        self._remember('none')
        self._link(0)
      return

    if self.probe_ts is not None:
      if self.present():
        self.probe_ts = None
        self._remember('jetlink-usb')
      elif now - self.probe_ts >= PROBE_S:
        self.probed = True
        self._end_probe()
      return
    if not self.probed and now - self.cable_ts >= GRACE_S:
      self.probe_ts = now
      self._link(1)
