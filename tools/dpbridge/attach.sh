#!/usr/bin/env bash
# Bring up hci0 on the WCN3990: power on, select the WCN3990 setup in hci_uart, attach the UART.
# Run by dpbridge-bt.service and stays in the foreground as btattach.
#   --addr        wait for hci0 and give it this unit's own address (the chip's default is shared by all units)
#   --print-addr  print that address
set -euo pipefail
TTY=${DPB_TTY:-/dev/ttyHS1}

# locally administered, derived from the device serial so it is stable and unique per unit
addr() {
  local serial
  serial=$(tr ' ' '\n' < "${DPB_CMDLINE:-/proc/cmdline}" | sed -n 's/^androidboot.serialno=//p')
  [ -n "$serial" ] || { echo "no serial in cmdline" >&2; return 1; }
  printf '%s' "$serial" | sha256sum | sed 's/^\(..\)\(..\)\(..\)\(..\)\(..\).*/02:\1:\2:\3:\4:\5/' | tr a-f A-F
}

case ${1:-} in
  --print-addr) addr; exit ;;
  --addr)
    a=$(addr)
    # the kernel only takes it while hci0 is powered off, which it is between setup and bluetoothd
    for _ in $(seq 40); do
      [ -e /sys/class/bluetooth/hci0 ] && btmgmt --index 0 public-addr "$a" > /dev/null 2>&1 && exit 0
      sleep 0.5
    done
    echo "could not set address $a" >&2; exit 1 ;;
esac

[ -e /lib/firmware/qca/crbtfw21.tlv ] || { echo "no BT firmware, run install_userspace.sh"; exit 1; }
rfkill unblock bluetooth
echo 1 > /sys/module/hci_uart/parameters/wcn3990
# the chip starts at 115200, hci_qca moves it to 3M after the power pulses
exec btattach -B "$TTY" -P qca -S 115200
