# dpbridge Bluetooth UI is shown whenever a dpbridge kernel runs (any build has working BT). Checked once:
# the kernel can't change without a reboot.
import functools
import os

WCN = "/sys/module/hci_uart/parameters/wcn3990"


@functools.cache
def bt_kernel() -> bool:
  try:
    return os.path.exists(WCN)
  except (OSError, ValueError):
    return False


# boot.py's "not now" on the kernel page; Settings > bluetooth removes it and reboots, so the page asks again
DECLINED = "/data/dpbridge_boot/declined"


def declined() -> bool:
  return os.path.exists(DECLINED)


def clear_declined():
  try:
    os.remove(DECLINED)
  except FileNotFoundError:
    pass
