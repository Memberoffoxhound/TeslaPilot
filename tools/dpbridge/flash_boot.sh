#!/usr/bin/env bash
# Put the dpbridge boot.img on the OTHER slot and make it active. The current slot is left stock, so
# going back is one abctl call (restore_boot.sh). Prints the plan only unless --yes is given.
# usage: flash_boot.sh [--yes] [boot.img]
set -euo pipefail

DIR=${DPB_DIR:-/data/dpbridge}
P=${DPB_PARTS:-/dev/disk/by-partlabel}
SUDO=${SUDO-sudo}
YES=0
IMG=$DIR/boot.img
for a in "$@"; do
  case $a in
    --yes) YES=1 ;;
    -*) echo "unknown flag $a"; exit 2 ;;
    *) IMG=$a ;;
  esac
done

die() { echo "refusing: $*" >&2; exit 1; }
run() { echo "+ $*"; if [ $YES = 1 ]; then "$@"; fi; }
sha() { $SUDO head -c "$2" "$1" | sha256sum | cut -d' ' -f1; }
size() { $SUDO blockdev --getsize64 "$1"; }

[ -f "$IMG" ] || die "no boot image at $IMG"
[ "$(head -c 8 "$IMG")" = "ANDROID!" ] || die "$IMG is not an Android boot image"
if [ -f "$IMG.sha256" ]; then
  [ "$(cut -d' ' -f1 "$IMG.sha256")" = "$(sha256sum "$IMG" | cut -d' ' -f1)" ] || die "$IMG does not match $IMG.sha256"
fi

cur=$(abctl --boot_slot)
case $cur in
  _a) oth=_b; onum=1 ;;
  _b) oth=_a; onum=0 ;;
  *) die "unknown boot slot '$cur'" ;;
esac
B=$DIR/backup
if [ -f "$B/stock_slot" ] && [ "$(cat "$B/stock_slot")" != "$cur" ]; then
  die "running the dpbridge slot $cur, flashing would overwrite stock $(cat "$B/stock_slot"). run restore_boot.sh --yes and reboot first"
fi
isz=$(stat -c %s "$IMG")
[ "$isz" -le "$(size "$P/boot$oth")" ] || die "image is larger than boot$oth"

# every A/B pair except boot, so the other slot runs the same firmware and system as today
parts=()
for p in "$P"/*_a; do
  n=$(basename "$p"); n=${n%_a}
  [ "$n" != boot ] && [ -e "$P/${n}_b" ] && parts+=("$n")
done
for n in "${parts[@]}"; do
  [ "$(size "$P/$n$cur")" = "$(size "$P/$n$oth")" ] || die "$n slots differ in size"
done

echo "current slot $cur, writing slot $oth, image $(sha256sum "$IMG" | cut -d' ' -f1)"
[ $YES = 1 ] || echo "dry run: nothing below is executed, pass --yes to flash"

# 1. back up both boot slots and prove the copies match the partitions; an older backup is kept aside
if [ -d "$B" ]; then
  run mv "$B" "$B.$(date +%Y%m%d-%H%M%S)"
fi
run mkdir -p "$B"
for s in _a _b; do
  run $SUDO dd if="$P/boot$s" of="$B/boot$s.img" bs=4M status=none
done
if [ $YES = 1 ]; then
  for s in _a _b; do
    [ "$(sha "$P/boot$s" "$(size "$P/boot$s")")" = "$(sha256sum < "$B/boot$s.img" | cut -d' ' -f1)" ] || die "backup of boot$s does not match"
  done
  (cd "$B" && sha256sum boot_a.img boot_b.img > SHA256SUMS)
  echo "$cur" > "$B/stock_slot"
fi

# 2. mirror the current slot into the other one
for n in "${parts[@]}"; do
  run $SUDO dd if="$P/$n$cur" of="$P/$n$oth" bs=4M conv=fsync status=none
  run $SUDO cmp "$P/$n$cur" "$P/$n$oth"
done

# 3. new kernel on the other slot only
run $SUDO dd if="$IMG" of="$P/boot$oth" bs=4M conv=fsync status=none
if [ $YES = 1 ]; then
  [ "$(sha "$P/boot$oth" "$isz")" = "$(sha256sum < "$IMG" | cut -d' ' -f1)" ] || die "boot$oth readback mismatch, slot not switched"
fi
run $SUDO abctl --set_active $onum

echo "done. reboot to try it; to go back: restore_boot.sh --yes (stock slot is $cur)"
