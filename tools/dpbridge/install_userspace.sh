#!/usr/bin/env bash
# Install the Bluetooth userspace on a comma 4 running the dpbridge kernel: firmware, bluez, bluez-alsa,
# bonds kept on /data, and the services that attach the chip and play A2DP on the speaker.
# Changes the read-only rootfs of the running slot (an AGNOS update undoes it). Prints the plan only unless --yes.
set -euo pipefail
YES=0
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
[ "${1:-}" = --yes ] && YES=1
put() { echo "+ write $1"; if [ $YES = 1 ]; then $SUDO tee "$1" > /dev/null; else cat > /dev/null; fi; }

[ -e /sys/module/hci_uart/parameters/wcn3990 ] || die "running kernel has no WCN3990 support, flash the dpbridge boot.img first"
[ -x "$DIR/attach.sh" ] || die "missing $DIR/attach.sh"
(cd "$DIR" && sha256sum -c --quiet firmware.sha256) || die "BT firmware in $DIR missing or not the pinned linux-firmware files, run deliver.sh push"
[ $YES = 1 ] || echo "dry run: pass --yes to install"

trap 'if [ $YES = 1 ]; then $SUDO /usr/comma/apt_teardown.sh; fi' EXIT
run $SUDO /usr/comma/apt_setup.sh

# WCN3990 firmware from linux-firmware (the comma 4 has no bluetooth partition), checked against firmware.sha256
run $SUDO mkdir -p /lib/firmware/qca
run $SUDO cp "$DIR/crbtfw21.tlv" "$DIR/crnv21.bin" /lib/firmware/qca/

run $SUDO apt-get update
run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends bluez bluez-alsa-utils alsa-utils

# /var is tmpfs, keep bonds on /data
run $SUDO mkdir -p "$DIR/bluetooth"

# shows up on phones as car audio
run $SUDO sed -i 's/^#\? *Class *=.*/Class = 0x240414/' /etc/bluetooth/main.conf
if [ $YES = 1 ]; then grep -q '^Class = 0x240414' /etc/bluetooth/main.conf || die "Class not set in main.conf"; fi

put /etc/systemd/system/dpbridge-bt.service <<UNIT
[Unit]
Description=dpbridge: attach the WCN3990 as hci0
Before=bluetooth.service
ConditionPathExists=/sys/module/hci_uart/parameters/wcn3990
# touch this file to keep the chip off on the next boot
ConditionPathExists=!$DIR/disable

[Service]
ExecStartPre=/bin/mkdir -p /var/lib/bluetooth
ExecStartPre=/bin/mount --bind $DIR/bluetooth /var/lib/bluetooth
ExecStart=$DIR/attach.sh
ExecStartPost=-$DIR/attach.sh --addr
ExecStopPost=-/bin/umount /var/lib/bluetooth
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

run $SUDO mkdir -p /etc/systemd/system/bluetooth.service.d /etc/systemd/system/bluealsa.service.d /etc/systemd/system/bluealsa-aplay.service.d
put /etc/systemd/system/bluetooth.service.d/dpbridge.conf <<UNIT
[Unit]
After=dpbridge-bt.service
Requires=dpbridge-bt.service
UNIT

# the comma only receives audio
put /etc/systemd/system/bluealsa.service.d/dpbridge.conf <<UNIT
[Service]
ExecStart=
ExecStart=/usr/bin/bluealsa -p a2dp-sink
UNIT

# opening dpb_a2dp once creates its volume control before any music plays
put /etc/systemd/system/bluealsa-aplay.service.d/dpbridge.conf <<UNIT
[Service]
ExecStartPre=-/usr/bin/aplay -q -D dpb_a2dp -t raw -f S16_LE -r 48000 -c 2 -s 1 /dev/zero
ExecStart=
ExecStart=/usr/bin/bluealsa-aplay -D dpb_a2dp
UNIT

run $SUDO systemctl daemon-reload
# apt enables these on install and they pull in dpbridge-bt, so they stay off until deliver.sh enable
run $SUDO systemctl disable bluetooth.service bluealsa.service bluealsa-aplay.service
run $SUDO systemctl stop bluetooth.service bluealsa.service bluealsa-aplay.service
# nothing is enabled: the first chip bring-up is done by hand, so a hang there can't loop every boot
echo "installed, not enabled. next: deliver.sh attach; if hci0 came up and SSH still works: deliver.sh enable"
