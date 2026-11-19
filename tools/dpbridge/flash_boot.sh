#!/usr/bin/env bash
# Put the dpbridge boot.img on the OTHER slot and make it active. The current slot is left stock, so
# going back is one abctl call (restore_boot.sh). Prints the plan only unless --yes is given.
# --rotate: a backup left stale by an AGNOS update is moved to backup.stale-<time> instead of refusing.
# usage: flash_boot.sh [--yes] [--rotate] [boot.img]
set -euo pipefail
YES=0
ROTATE=0
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
IMG=$DIR/boot.img
for a in "$@"; do
  case $a in
    --yes) YES=1 ;;
    --rotate) ROTATE=1 ;;
    -*) echo "unknown flag $a"; exit 2 ;;
    *) IMG=$a ;;
  esac
done

# the A/B partitions AGNOS updates (agnos.json) minus boot; the rest stay as they are
MIRROR="xbl xbl_config abl aop devcfg system"
AGNOS=20.6

grep -q mici < <(tr -d '\0' < "${DPB_MODEL:-/sys/firmware/devicetree/base/model}") || die "not a comma 4 (mici)"
[ "$(tr -d '[:space:]' < "${DPB_VERSION:-/VERSION}")" = $AGNOS ] || die "boot.img is built for AGNOS $AGNOS"
[ -f "$IMG" ] || die "no boot image at $IMG"
[ -f "$IMG.sha256" ] || die "no $IMG.sha256"
[ "$(cut -d' ' -f1 "$IMG.sha256")" = "$(fsha "$IMG")" ] || die "$IMG does not match $IMG.sha256"
[ "$(head -c 8 "$IMG")" = "ANDROID!" ] || die "$IMG is not an Android boot image"
isz=$(stat -c %s "$IMG")

cur=$(abctl --boot_slot)
oth=$(other "$cur")
# every partition this touches is a block device, checked before anything is written (tests use files)
for n in $MIRROR boot; do
  for s in "$cur" "$oth"; do
    test "${DPB_BLK:--b}" "$P/$n$s" || die "$P/$n$s is not a block device"
  done
done
# --rotate replaces a backup; on any dpbridge kernel the live backup may be the only stock copy
[ $ROTATE = 1 ] && [ -e "${DPB_WCN:-/sys/module/hci_uart/parameters/wcn3990}" ] && die "a dpbridge kernel is running, restore_boot.sh --yes and reboot first"
stale() {
  [ $ROTATE = 1 ] || die "$1 (AGNOS update?). move $B aside and run again"
  echo "$1, keeping the old backup"
  run mv "$B" "$B.stale-$(date +%Y%m%d-%H%M%S)"
}
# never from the dpbridge slot: the other slot is the stock fallback
[ "$(dsha "$P/boot$cur" "$isz")" = "$(fsha "$IMG")" ] && die "running the dpbridge slot $cur. run restore_boot.sh --yes and reboot first"
if [ -f "$B/stock_slot" ]; then
  if [ "$(cat "$B/stock_slot")" != "$cur" ]; then
    stale "boot slot changed since the last flash"
  elif ! grep -q "^$(dsha "$P/boot$cur" "$(size "$P/boot$cur")")  boot$cur.img" "$B/SHA256SUMS"; then
    stale "boot$cur changed since the last backup"
  fi
fi
[ "$isz" -le "$(size "$P/boot$oth")" ] || die "image is larger than boot$oth"
for n in $MIRROR; do
  [ "$(size "$P/$n$cur")" = "$(size "$P/$n$oth")" ] || die "$n slots differ in size"
done

echo "current slot $cur, writing slot $oth, image $(fsha "$IMG")"
[ $YES = 1 ] || echo "dry run: nothing below is executed, pass --yes to flash"

progress "backing up" 45
# 1. back up both boot slots and prove the copies match flash; an older backup is kept aside
if [ -d "$B" ]; then
  run mv "$B" "$B.$(date +%Y%m%d-%H%M%S)"
fi
run mkdir -p "$B"
for s in _a _b; do
  run $SUDO dd if="$P/boot$s" of="$B/boot$s.img" bs=4M status=none
done
if [ $YES = 1 ]; then
  for s in _a _b; do
    [ "$(dsha "$P/boot$s" "$(size "$P/boot$s")")" = "$(fsha "$B/boot$s.img")" ] || die "backup of boot$s does not match"
  done
  (cd "$B" && sha256sum boot_a.img boot_b.img > SHA256SUMS)
  echo "$cur" > "$B/stock_slot"
fi

# 2. nothing boots the other slot while it is half written
run $SUDO abctl --set_unbootable "$(slot_num "$oth")"

# 3. mirror the current slot into the other one, skipping what already matches
# compare and copy with O_DIRECT: cmp can agree from the page cache when flash still differs
i=0
for n in $MIRROR; do
  progress "writing slot ${oth#_}" $((55 + i * 4)); i=$((i + 1))
  if [ "$(dsha "$P/$n$cur" "$(size "$P/$n$cur")")" = "$(dsha "$P/$n$oth" "$(size "$P/$n$oth")")" ]; then
    echo "  $n already matches"
    continue
  fi
  run $SUDO dd if="$P/$n$cur" of="$P/$n$oth" bs=4M iflag=direct conv=fsync status=none
  if [ $YES = 1 ]; then
    progress "reading back" $((55 + i * 4 - 2))
    sz=$(size "$P/$n$cur")
    [ "$(dsha "$P/$n$cur" "$sz")" = "$(dsha "$P/$n$oth" "$sz")" ] || die "$n$oth readback mismatch, slot not switched"
  fi
done

# 4. new kernel on the other slot only
progress "writing slot ${oth#_}" 80
run $SUDO dd if="$IMG" of="$P/boot$oth" bs=4M conv=fsync status=none
if [ $YES = 1 ]; then
  progress "reading back" 90
  [ "$(dsha "$P/boot$oth" "$isz")" = "$(fsha "$IMG")" ] || die "boot$oth readback mismatch, slot not switched"
fi
progress "switching slot" 98
activate "$(slot_num "$oth")"

echo "done. reboot to try it; to go back: restore_boot.sh --yes (stock slot is $cur)"
