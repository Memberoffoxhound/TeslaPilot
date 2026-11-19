#!/usr/bin/env bash
# Install the Bluetooth userspace on a comma 4 running the dpbridge kernel: firmware, bluez, bluez-obexd,
# bluez-alsa, bonds kept on /data, and the services that attach the chip and play A2DP on the speaker.
# Packages are apt-get download + dpkg --ignore-depends=udev --force-confold, skipped if their files are present.
# Never apt-get install, never apt --fix-broken, never install udev. An AGNOS update undoes the rootfs changes.
# Prints the plan only unless --yes.
set -euo pipefail
YES=0
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
[ "${1:-}" = --yes ] && YES=1
put() { echo "+ write $1"; if [ $YES = 1 ]; then $SUDO tee "$1" > /dev/null; else cat > /dev/null; fi; }

[ -e /sys/module/hci_uart/parameters/wcn3990 ] || die "running kernel has no WCN3990 support, flash the dpbridge boot.img first"
[ -x "$DIR/attach.sh" ] || die "missing $DIR/attach.sh"
(cd "$DIR" && sha256sum -c --quiet firmware.sha256) || die "BT firmware in $DIR missing or not the pinned files, run deliver.sh push"
[ $YES = 1 ] || echo "dry run: pass --yes to install"

MNT=/tmp/dpbridge-btimg
# umount fails once the success path has unmounted; it must not stop the teardown or the exit status
trap 'if [ $YES = 1 ]; then $SUDO umount "$MNT" 2> /dev/null || true; $SUDO /usr/comma/apt_teardown.sh; fi' EXIT
run $SUDO /usr/comma/apt_setup.sh

# WCN3990 firmware (the comma 4 has no bluetooth partition). btqca loads qca/crbtfw<rev>.tlv and qca/crnv<rev>.bin
# for the chip's rom revision: linux-firmware for rev 21, comma's own files from agnos-builder bluetooth.img for 11 and 20
# comma's rev 21 pair is in the image too (other builds); to use it, add crbtfw21.tlv crnv21.bin to the list below and
# put their hashes (2a428590..., 18cc38ff..., see README) in qca.sha256 in place of linux-firmware's
comma_fw() {
  local f src
  for f in crbtfw11.tlv crnv11.bin crbtfw20.tlv crnv20.bin; do
    src=$(find "$MNT" -iname "$f" | head -n 1)
    [ -n "$src" ] || die "$f not in bluetooth.img"
    $SUDO cp "$src" "/lib/firmware/qca/$f"
  done
}
run $SUDO mkdir -p /lib/firmware/qca "$MNT"
run $SUDO cp "$DIR/crbtfw21.tlv" "$DIR/crnv21.bin" /lib/firmware/qca/
run $SUDO mount -o loop,ro,shortname=lower "$DIR/bluetooth.img" "$MNT"
run comma_fw
run $SUDO umount "$MNT"
if [ $YES = 1 ]; then (cd /lib/firmware/qca && sha256sum -c --quiet "$DIR/qca.sha256") || die "installed BT firmware does not match qca.sha256"; fi

# AGNOS has no udev package, and apt is already broken on netplan/network-manager needing udev.
# Never apt-get install, never apt --fix-broken, never install real udev.
# /var is tmpfs and apt_setup.sh resets the dpkg database from /usr/default, so dpkg never remembers these;
# check the installed files instead. Same download + dpkg method and list already used on this comma.
PKGS="bluez bluez-obexd bluez-alsa-utils libasound2-plugin-bluez libical3t64 libldacbt-abr2 libldacbt-enc2 libsbc1"
L=/usr/lib/aarch64-linux-gnu
MARKS="/usr/libexec/bluetooth/bluetoothd /usr/libexec/bluetooth/obexd /usr/bin/bluealsa /usr/bin/bluealsa-aplay
$L/alsa-lib/libasound_module_pcm_bluealsa.so $L/libical.so.3 $L/libldacBT_abr.so.2 $L/libldacBT_enc.so.2 $L/libsbc.so.1"
missing=""
for f in $MARKS; do [ -e "$f" ] || missing="$missing $f"; done
if [ -z "$missing" ]; then
  echo "  bluetooth packages already on the rootfs"
else
  echo "  missing:$missing"
  run $SUDO apt-get update
  echo "+ apt-get download $PKGS"
  echo "+ dpkg --ignore-depends=udev --force-confold -i /tmp/dpbridge-debs/*.deb"
  if [ $YES = 1 ]; then
    $SUDO mkdir -p /tmp/dpbridge-debs
    $SUDO rm -f /tmp/dpbridge-debs/*.deb
    # shellcheck disable=SC2086  # PKGS is a list of package names
    (cd /tmp/dpbridge-debs && $SUDO apt-get download $PKGS)
    # something can remount / read-only while apt runs; make sure it is writable for dpkg
    $SUDO mount -o rw,remount /
    $SUDO dpkg --ignore-depends=udev --force-confold -i /tmp/dpbridge-debs/*.deb
  fi
fi

if [ $YES = 1 ]; then $SUDO mount -o rw,remount /; fi

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

# opening dpb_a2dp once creates its volume control (softvol starts it at full), then it is zeroed so nothing
# plays before dpb_a2dp sets it; without the audio.sh link there is no dpb_a2dp, so it stays off
put /etc/systemd/system/bluealsa-aplay.service.d/dpbridge.conf <<UNIT
[Unit]
ConditionPathIsSymbolicLink=/etc/asound.conf
[Service]
ExecStartPre=-/usr/bin/aplay -q -D dpb_a2dp -t raw -f S16_LE -r 48000 -c 2 -s 1 /dev/zero
ExecStartPre=/usr/bin/amixer -c0 -q cset name='dpbridge A2DP Playback Volume' 0%
ExecStart=
ExecStart=/usr/bin/bluealsa-aplay -D dpb_a2dp
UNIT

run $SUDO systemctl daemon-reload
# apt enables these on install and they pull in dpbridge-bt, so they stay off until deliver.sh enable
run $SUDO systemctl disable bluetooth.service bluealsa.service bluealsa-aplay.service
run $SUDO systemctl stop bluetooth.service bluealsa.service bluealsa-aplay.service
# nothing is enabled: the first chip bring-up is done by hand, so a hang there can't loop every boot
echo "installed, not enabled. next: deliver.sh attach; if hci0 came up and SSH still works: deliver.sh enable"
