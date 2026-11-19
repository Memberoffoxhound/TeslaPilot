#!/usr/bin/env bash
# The dpbridge installer, run with openpilot down: Bluetooth firmware, the dpbridge BlueZ build, bluez-alsa,
# bonds kept on /data, the services, and last the kernel on the inactive slot with one reboot as the final step.
# On a stock kernel it always flashes, also after a restore; /data/dpbridge/disable or a failed try stop it unless --reflash.
# Debs are kept on /data and installed with dpkg --ignore-depends=udev --force-confold, skipped if present.
# Never apt-get install, never apt --fix-broken, never install udev. An AGNOS update undoes the rootfs changes.
# Prints the plan only unless --yes.
set -euo pipefail
YES=0
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
REFLASH=0
for a in "$@"; do
  case $a in
    --yes) YES=1 ;;
    --reflash) REFLASH=1 ;;
    *) echo "usage: install_userspace.sh [--yes] [--reflash]"; exit 2 ;;
  esac
done
HERE=$(cd "$(dirname "$0")" && pwd)
put() { echo "+ write $1"; if [ $YES = 1 ]; then $SUDO tee "$1" > /dev/null; else cat > /dev/null; fi; }
REBOOT=${DPB_REBOOT:-reboot}
KSH=(bash "$HERE/kernel.sh")
[ $YES = 1 ] || echo "dry run: pass --yes to install"

# the kernel step, last: flash the inactive slot when the stock kernel runs; 0 = rebooting needed
kernel_step() {
  local st a=(flash --no-reboot)
  st=$($SUDO "${KSH[@]}" status | sed -n 's/^state=//p')
  case $st in
    ok) echo "  dpbridge kernel running"; return 1 ;;
    outdated) echo "  an older dpbridge kernel runs: restore_boot.sh --yes, reboot, then install again"; return 1 ;;
    off) if [ $REFLASH = 0 ]; then echo "  kernel flash is off ($DIR/disable), pass --reflash"; return 1; fi ;;
    failed) if [ $REFLASH = 0 ]; then echo "  the last flash failed and was kept off, pass --reflash"; return 1; fi ;;
  esac
  [ $YES = 1 ] && a+=(--yes)
  [ $REFLASH = 1 ] && a+=(--retry)
  $SUDO "${KSH[@]}" "${a[@]}" || die "kernel flash failed, nothing was switched"
  [ $YES = 1 ]
}

echo "[1/4] last kernel flash"
if [ $YES = 1 ]; then $SUDO "${KSH[@]}" post-boot --yes; else $SUDO "${KSH[@]}" post-boot; fi

echo "[2/4] BT firmware"

# BT firmware and the unit scripts on /data, no Mac needed. They stay there across AGNOS updates.
# One release tarball pinned in firmware/btfw.env (linux-firmware files and comma's bluetooth.img), each file
# checked against firmware/firmware.sha256.
# shellcheck source=firmware/btfw.env
source "$HERE/firmware/btfw.env"
fw_ok() { (cd "$DIR" && sha256sum -c --quiet "$HERE/firmware/firmware.sha256") > /dev/null 2>&1; }
get_fw() {
  $SUDO mkdir -p "$DIR/debs"
  if [ ! -f "$DIR/debs/$BTFW_TAR" ] || [ "$(fsha "$DIR/debs/$BTFW_TAR")" != "$BTFW_SHA" ]; then
    $SUDO curl -fL --retry 5 -C - -o "$DIR/debs/$BTFW_TAR.part" "$BTFW_URL" || die "firmware download failed: $BTFW_URL"
    [ "$(fsha "$DIR/debs/$BTFW_TAR.part")" = "$BTFW_SHA" ] || { $SUDO rm -f "$DIR/debs/$BTFW_TAR.part"; die "$BTFW_TAR does not match btfw.env"; }
    $SUDO mv "$DIR/debs/$BTFW_TAR.part" "$DIR/debs/$BTFW_TAR"
  fi
  $SUDO tar -xf "$DIR/debs/$BTFW_TAR" -C "$DIR"
  fw_ok || die "BT firmware in $DIR does not match firmware.sha256"
}
if fw_ok; then
  echo "  BT firmware already on /data"
else
  echo "+ fetch BT firmware into $DIR ($BTFW_TAR)"
  [ $YES = 1 ] && get_fw
fi
run $SUDO mkdir -p "$DIR"
for f in attach.sh asound.conf firmware/firmware.sha256 firmware/qca.sha256; do
  run $SUDO install -m "$([ "${f%.sh}" != "$f" ] && echo 0755 || echo 0644)" "$HERE/$f" "$DIR/$(basename "$f")"
done

echo "[3/4] Bluetooth packages and services"
MNT=/tmp/dpbridge-btimg
# obexd exits without one server plugin and transport; OPP stays, rejected with no agent
OBEX_OFF=pcsuite,ftp,irmc,pbap,mas,mns
# umount fails once the success path has unmounted; it must not stop the teardown or the exit status
trap 'if [ $YES = 1 ]; then $SUDO umount "$MNT" 2> /dev/null || true; $SUDO /usr/comma/apt_teardown.sh; fi' EXIT
teardown() { if [ $YES = 1 ]; then $SUDO umount "$MNT" 2> /dev/null || true; $SUDO /usr/comma/apt_teardown.sh; fi; }
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
# check the installed files instead. Every deb is kept on /data, so after an AGNOS update this reinstalls offline.
# BlueZ is the dpbridge build pinned in bluez/bluez.env (experimental API, obexd with BIP, no Evolution libs);
# the rest are noble debs from apt.
# shellcheck source=bluez/bluez.env
source "$HERE/bluez/bluez.env"
DEBS=$DIR/debs
BZ=$DEBS/bluez-$BLUEZ_VER
PKGS="bluez-alsa-utils libasound2-plugin-bluez libical3t64 libldacbt-abr2 libldacbt-enc2 libsbc1"
L=/usr/lib/aarch64-linux-gnu
MARKS="/usr/libexec/bluetooth/bluetoothd /usr/libexec/bluetooth/obexd /usr/bin/bluealsa /usr/bin/bluealsa-aplay
$L/alsa-lib/libasound_module_pcm_bluealsa.so $L/libical.so.3 $L/libldacBT_abr.so.2 $L/libldacBT_enc.so.2 $L/libsbc.so.1"

# release tarball on /data, sha pinned in git; a copy pushed by deliver.sh skips the download
bluez_debs() {
  $SUDO mkdir -p "$DEBS"
  if [ ! -f "$DEBS/$BLUEZ_TAR" ] || [ "$(fsha "$DEBS/$BLUEZ_TAR")" != "$BLUEZ_SHA" ]; then
    $SUDO curl -fL --retry 5 --retry-delay 3 -C - -o "$DEBS/$BLUEZ_TAR.part" "$BLUEZ_URL" || die "BlueZ download failed: $BLUEZ_URL"
    [ "$(fsha "$DEBS/$BLUEZ_TAR.part")" = "$BLUEZ_SHA" ] || { $SUDO rm -f "$DEBS/$BLUEZ_TAR.part"; die "$BLUEZ_TAR does not match bluez.env"; }
    $SUDO mv "$DEBS/$BLUEZ_TAR.part" "$DEBS/$BLUEZ_TAR"
  fi
  $SUDO rm -rf "$BZ"
  $SUDO mkdir -p "$BZ"
  $SUDO tar -xf "$DEBS/$BLUEZ_TAR" -C "$BZ"
  (cd "$BZ" && sha256sum -c --quiet SHA256SUMS) || die "debs in $BLUEZ_TAR are damaged"
}

# noble debs, downloaded once into $DEBS/apt
apt_debs() {
  local p
  for p in $PKGS; do
    compgen -G "$DEBS/apt/${p}_*_arm64.deb" > /dev/null || { $SUDO apt-get update && break; }
  done
  $SUDO mkdir -p "$DEBS/apt"
  for p in $PKGS; do
    compgen -G "$DEBS/apt/${p}_*_arm64.deb" > /dev/null || (cd "$DEBS/apt" && $SUDO apt-get download "$p")
  done
}

missing=""
for f in $MARKS; do [ -e "$f" ] || missing="$missing $f"; done
have=$(/usr/libexec/bluetooth/bluetoothd --version 2> /dev/null || true)
[ "$have" = "$BLUEZ_VER" ] || missing="$missing bluetoothd-$BLUEZ_VER(have ${have:-none})"
if [ -z "$missing" ]; then
  echo "  bluetooth packages already on the rootfs, BlueZ $have"
else
  echo "  missing:$missing"
  echo "+ BlueZ $BLUEZ_VER from $DEBS/$BLUEZ_TAR (sha $BLUEZ_SHA)"
  echo "+ apt-get download $PKGS into $DEBS/apt (once)"
  echo "+ dpkg --ignore-depends=udev --force-confold -i $BZ/*.deb $DEBS/apt/*.deb"
  if [ $YES = 1 ]; then
    bluez_debs
    apt_debs
    # something can remount / read-only while apt runs; make sure it is writable for dpkg
    $SUDO mount -o rw,remount /
    $SUDO dpkg --ignore-depends=udev --force-confold -i "$BZ"/*.deb "$DEBS"/apt/*.deb
    have=$(/usr/libexec/bluetooth/bluetoothd --version 2> /dev/null || true)
    [ "$have" = "$BLUEZ_VER" ] || die "bluetoothd is ${have:-missing} after install, wanted $BLUEZ_VER"
  fi
fi

if [ $YES = 1 ]; then $SUDO mount -o rw,remount /; fi

# /var is tmpfs, keep bonds on /data
run $SUDO mkdir -p "$DIR/bluetooth"

# shows up on phones as car audio
run $SUDO sed -i 's/^#\? *Class *=.*/Class = 0x240414/' /etc/bluetooth/main.conf
# MediaPlayer1 ObexPort and ImgHandle (cover art) are experimental; also -E in the unit below
run $SUDO sed -i 's/^#\? *Experimental *=.*/Experimental = true/' /etc/bluetooth/main.conf
if [ $YES = 1 ]; then
  grep -q '^Experimental = true' /etc/bluetooth/main.conf || echo 'Experimental = true' | $SUDO tee -a /etc/bluetooth/main.conf >/dev/null
  grep -q '^Class = 0x240414' /etc/bluetooth/main.conf || die "Class not set in main.conf"
  grep -q '^Experimental = true' /etc/bluetooth/main.conf || die "Experimental not set in main.conf"
fi

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
# setup takes about 2 s and --addr at most 30 s
TimeoutStartSec=60

[Install]
WantedBy=multi-user.target
UNIT

run $SUDO mkdir -p /etc/systemd/system/bluetooth.service.d /etc/systemd/system/bluealsa.service.d /etc/systemd/system/bluealsa-aplay.service.d
put /etc/systemd/system/bluetooth.service.d/dpbridge.conf <<UNIT
[Unit]
After=dpbridge-bt.service
Requires=dpbridge-bt.service
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd -E
UNIT

# cover art: obexd as root on the system bus (5.83 -s) so nowplaying needs no session bus.
# PBAP, MAP and FTP servers off; only the BIP client is used.
put /etc/systemd/system/dpbridge-obex.service <<UNIT
[Unit]
Description=dpbridge: obexd for AVRCP cover art
After=bluetooth.service
Requires=bluetooth.service
PartOf=bluetooth.service

[Service]
Type=dbus
BusName=org.bluez.obex
ExecStart=/usr/libexec/bluetooth/obexd -n -s -P $OBEX_OFF
Restart=on-failure
RestartSec=5
UNIT

# the comma only receives audio
put /etc/systemd/system/bluealsa.service.d/dpbridge.conf <<UNIT
[Service]
ExecStart=
ExecStart=/usr/bin/bluealsa -p a2dp-sink
UNIT

# A2DP goes to a FIFO in /run/dpbridge that soundd reads; the global ALSA config is left alone
put /etc/systemd/system/bluealsa-aplay.service.d/dpbridge.conf <<UNIT
[Unit]
# start once the controller and bluealsa are up
After=dpbridge-bt.service bluetooth.service bluealsa.service
Requires=bluealsa.service
[Service]
# the 4.9 kernel has no user namespaces, the stock PrivateUsers=true fails with 217/USER
PrivateUsers=no
RestartSec=5
RuntimeDirectory=dpbridge
RuntimeDirectoryMode=0755
RuntimeDirectoryPreserve=yes
ReadWritePaths=/run/dpbridge
Environment=ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf:$DIR/asound.conf
ExecStartPre=/bin/sh -c '[ -p /run/dpbridge/a2dp.fifo ] || mkfifo -m 0666 /run/dpbridge/a2dp.fifo'
ExecStart=
ExecStart=/usr/bin/bluealsa-aplay -D dpb_a2dp
UNIT

# radio helper: the Settings toggle starts and stops the units; no remount for start/stop
if [ -x "$HERE/radio.sh" ]; then
  run $SUDO cp "$HERE/radio.sh" "$DIR/radio.sh"
  run $SUDO chmod 0755 "$DIR/radio.sh"
fi
put /etc/systemd/system/dpbridge-radio.service <<UNIT
[Unit]
Description=dpbridge: start or stop Bluetooth from DpbBluetooth
After=local-fs.target
ConditionPathExists=/sys/module/hci_uart/parameters/wcn3990

[Service]
Type=simple
ExecStart=$DIR/radio.sh --watch
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

run $SUDO systemctl daemon-reload
# apt enables these on install and they pull in dpbridge-bt; the helper starts them when the toggle is on
run $SUDO systemctl disable bluetooth.service bluealsa.service bluealsa-aplay.service dpbridge-obex.service
run $SUDO systemctl stop bluetooth.service bluealsa.service bluealsa-aplay.service dpbridge-obex.service
run $SUDO systemctl enable dpbridge-radio.service
if [ $YES = 1 ]; then
  run $SUDO systemctl restart dpbridge-radio.service || run $SUDO systemctl start dpbridge-radio.service
fi

echo "[4/4] kernel"
if kernel_step; then
  # the reboot is the final step, after the apt teardown
  teardown
  trap - EXIT
  echo "installed. rebooting into the dpbridge kernel"
  $SUDO "$REBOOT"
  exit 0
fi
echo "installed. the Bluetooth toggle in Settings starts the radio; no deliver.sh enable needed"
