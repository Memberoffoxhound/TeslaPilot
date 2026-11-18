#!/usr/bin/env bash
# Go back to the stock kernel: re-activate the slot that was running before flash_boot.sh.
# --write also copies the backed up boot image over the dpbridge slot. Prints the plan only unless --yes.
set -euo pipefail

DIR=${DPB_DIR:-/data/dpbridge}
P=${DPB_PARTS:-/dev/disk/by-partlabel}
SUDO=${SUDO-sudo}
B=$DIR/backup
YES=0; WRITE=0
for a in "$@"; do
  case $a in
    --yes) YES=1 ;;
    --write) WRITE=1 ;;
    *) echo "usage: restore_boot.sh [--yes] [--write]"; exit 2 ;;
  esac
done

die() { echo "refusing: $*" >&2; exit 1; }
run() { echo "+ $*"; if [ $YES = 1 ]; then "$@"; fi; }

[ -f "$B/stock_slot" ] || die "no $B/stock_slot, flash_boot.sh never ran here"
(cd "$B" && sha256sum -c --quiet SHA256SUMS) || die "backups in $B are damaged"
stock=$(cat "$B/stock_slot")
case $stock in
  _a) num=0; oth=_b ;;
  _b) num=1; oth=_a ;;
  *) die "bad stock slot '$stock'" ;;
esac

[ $YES = 1 ] || echo "dry run: pass --yes to execute"
if [ $WRITE = 1 ]; then
  run $SUDO dd if="$B/boot$oth.img" of="$P/boot$oth" bs=4M conv=fsync status=none
fi
run $SUDO abctl --set_active $num
echo "stock slot $stock active after reboot"
