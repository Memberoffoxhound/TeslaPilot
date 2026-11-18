#!/usr/bin/env bash
# Install the Bluetooth userspace on a comma 4 running the dpbridge kernel: firmware, bluez, bluez-alsa,
# bonds kept on /data, and the services that attach the chip and play A2DP on the speaker.
# Changes the read-only rootfs of the running slot (an AGNOS update undoes it). Prints the plan only unless --yes.
set -euo pipefail

DIR=${DPB_DIR:-/data/dpbridge}
P=/dev/disk/by-partlabel
SUDO=${SUDO-sudo}
YES=0
[ "${1:-}" = --yes ] && YES=1

die() { echo "refusing: $*" >&2; exit 1; }
run() { echo "+ $*"; if [ $YES = 1 ]; then "$@"; fi; }
put() { echo "+ write $1"; if [ $YES = 1 ]; then $SUDO tee "$1" > /dev/null; else cat > /dev/null; fi; }

[ -e /sys/module/hci_uart/parameters/wcn3990 ] || die "running kernel has no WCN3990 support, flash the dpbridge boot.img first"
[ -x "$DIR/attach.sh" ] || die "missing $DIR/attach.sh"
slot=$(abctl --boot_slot)
[ -e "$P/bluetooth$slot" ] || die "no bluetooth$slot partition"
[ $YES = 1 ] || echo "dry run: pass --yes to install"

run $SUDO /usr/comma/apt_setup.sh
[ $YES = 1 ] && trap '$SUDO /usr/comma/apt_teardown.sh' EXIT

# firmware ships on the bluetooth partition; the kernel wants lowercase names under qca/
M=$(mktemp -d)
run $SUDO mount -o ro "$P/bluetooth$slot" "$M"
run $SUDO mkdir -p /lib/firmware/qca
run $SUDO cp "$M/image/crbtfw21.tlv" /lib/firmware/qca/crbtfw21.tlv
run $SUDO cp "$M/image/crnv21.bin" /lib/firmware/qca/crnv21.bin
run $SUDO umount "$M"

run $SUDO apt-get update
run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends bluez bluez-alsa-utils alsa-utils

# /var is tmpfs, keep bonds on /data
run $SUDO mkdir -p "$DIR/bluetooth"

put /etc/systemd/system/dpbridge-bt.service <<UNIT
[Unit]
Description=dpbridge: attach the WCN3990 as hci0
Before=bluetooth.service
ConditionPathExists=/sys/module/hci_uart/parameters/wcn3990

[Service]
ExecStartPre=/bin/mkdir -p /var/lib/bluetooth
ExecStartPre=/bin/mount --bind $DIR/bluetooth /var/lib/bluetooth
ExecStart=$DIR/attach.sh
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

# A2DP goes out on its own front end so it never fights soundd for MultiMedia1
put /etc/systemd/system/bluealsa-aplay.service.d/dpbridge.conf <<UNIT
[Service]
ExecStartPre=/usr/bin/amixer -c0 cset name='SEC_MI2S_RX Audio Mixer MultiMedia2' 1
ExecStart=
ExecStart=/usr/bin/bluealsa-aplay -D plughw:0,1
UNIT

run $SUDO systemctl daemon-reload
run $SUDO systemctl enable dpbridge-bt.service bluetooth.service bluealsa.service bluealsa-aplay.service
echo "installed. sudo reboot, then run test_bt.sh"
