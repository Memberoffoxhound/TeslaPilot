#!/usr/bin/env bash
# Bring up hci0 on the WCN3990: power on, select the WCN3990 setup in hci_uart, attach the UART.
# Run by dpbridge-bt.service and stays in the foreground as btattach.
set -euo pipefail
TTY=${DPB_TTY:-/dev/ttyHS1}

[ -e /lib/firmware/qca/crbtfw21.tlv ] || { echo "no BT firmware, run install_userspace.sh"; exit 1; }
rfkill unblock bluetooth
echo 1 > /sys/module/hci_uart/parameters/wcn3990
# the chip starts at 115200, hci_qca moves it to 3M after the power pulses
exec btattach -B "$TTY" -P qca -S 115200
