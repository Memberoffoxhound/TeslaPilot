# dpbridge Bluetooth UI is shown only on the right kernel. Checked once: the kernel can't change without a reboot.
import functools
import os

WCN = "/sys/module/hci_uart/parameters/wcn3990"
# kernel.sh's running-slot result, "<boot_id> ok|outdated"; only trusted when written this boot
RUNNING = "/data/dpbridge/kernel/running"
BOOT_ID = "/proc/sys/kernel/random/boot_id"


def _read(path: str) -> str:
  try:
    with open(path) as f:
      return f.read().strip()
  except OSError:
    return ""


@functools.cache
def bt_kernel() -> bool:
  if not os.path.exists(WCN):
    return False
  cached = _read(RUNNING).split()
  return not (len(cached) == 2 and cached[0] == _read(BOOT_ID) and cached[1] == "outdated")
