#!/usr/bin/env bash
# Go back to the stock kernel: re-activate the slot that was running before flash_boot.sh.
# --write also copies the stock kernel over the dpbridge slot, which matches the system mirrored there.
# The next boot reruns the installer (slot changed) and it flashes dpbridge again unless /data/dpbridge/disable
# exists. Prints the plan only unless --yes.
set -euo pipefail
YES=0; WRITE=0
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
for a in "$@"; do
  case $a in
    --yes) YES=1 ;;
    --write) WRITE=1 ;;
    *) echo "usage: restore_boot.sh [--yes] [--write]"; exit 2 ;;
  esac
done

[ -f "$B/stock_slot" ] || die "no $B/stock_slot, flash_boot.sh never ran here"
(cd "$B" && sha256sum -c --quiet SHA256SUMS) || die "backups in $B are damaged"
stock=$(cat "$B/stock_slot")
oth=$(other "$stock")

[ $YES = 1 ] || echo "dry run: pass --yes to execute"
if [ $WRITE = 1 ]; then
  img=$B/boot$stock.img
  run $SUDO dd if="$img" of="$P/boot$oth" bs=4M conv=fsync status=none
  if [ $YES = 1 ]; then
    [ "$(dsha "$P/boot$oth" "$(stat -c %s "$img")")" = "$(fsha "$img")" ] || die "boot$oth readback mismatch"
  fi
fi
activate "$(slot_num "$stock")"
echo "stock slot $stock active after reboot"
# the slot change reruns the installer at the next boot, which reflashes a stock kernel
echo "to stay on stock: touch $DIR/disable before rebooting, or the next boot flashes dpbridge again"
