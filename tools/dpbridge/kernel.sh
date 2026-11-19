#!/usr/bin/env bash
# Automatic kernel flash, run by install_userspace.sh and by kerneld (offroad). No menu: every check is here.
#   status              key=value lines (state=ok|offer|failed|pending|onroad|no_space|unsupported_*)
#   fetch               get boot.img from the release, checked against the pinned sha
#   flash [--yes] [--retry]  inactive slot only, read back, then one reboot. A failed try for this
#                       image, AGNOS and slot is not repeated without --retry
#   post-boot [--yes]   after the reboot: record the result, install the Bluetooth userspace
set -euo pipefail
YES=0
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib.sh
source "$HERE/lib.sh"
# shellcheck source=firmware/kernel.env
source "${DPB_KERNEL_ENV:-$HERE/firmware/kernel.env}"
WCN=${DPB_WCN:-/sys/module/hci_uart/parameters/wcn3990}
K=$DIR/kernel
IMG=$DIR/boot.img
KEEP=${DPB_KEEP_BACKUPS:-3}
REBOOT=${DPB_REBOOT:-reboot}
CURL=${DPB_CURL:-curl}
ONROAD=${DPB_ONROAD:-/data/params/d/IsOnroad}

model_ok() { grep -q mici < <(tr -d '\0' < "${DPB_MODEL:-/sys/firmware/devicetree/base/model}"); }
agnos() { tr -d '[:space:]' < "${DPB_VERSION:-/VERSION}"; }
image_state() {
  [ -f "$IMG" ] || { echo missing; return; }
  [ "$(stat -c %s "$IMG")" = "$BOOT_SIZE" ] && [ "$(fsha "$IMG")" = "$BOOT_SHA" ] && echo ok || echo bad
}
onroad() { [ "$(tr -d '[:space:]' < "$ONROAD" 2> /dev/null || true)" = 1 ]; }
# what a failed try is keyed on; an AGNOS update changes the slot or version, so it tries again
try_key() { echo "$BOOT_SHA $(agnos) $(abctl --boot_slot)"; }
failed_here() { [ -f "$K/failed" ] && [ "$(cat "$K/failed")" = "$(try_key)" ]; }
free_mb() { if [ -n "${DPB_FREE_MB:-}" ]; then echo "$DPB_FREE_MB"; else df -Pm "$DIR" | awk 'NR==2{print $4}'; fi; }
need_mb() {
  local cur img=$BOOT_SIZE; cur=$(abctl --boot_slot)
  [ "$(image_state)" = ok ] && img=0
  # image, two boot backups, 64 MB spare
  echo $(( (img + 2 * $(size "$P/boot$cur")) / 1048576 + 64 ))
}

status() {
  mkdir -p "$DIR"
  local cur oth st=offer
  cur=$(abctl --boot_slot)
  oth=$(other "$cur")
  if [ -e "$WCN" ]; then st=ok
  elif ! model_ok; then st=unsupported_device
  elif [ "$(agnos)" != "$BOOT_AGNOS" ]; then st=unsupported_agnos
  elif [ -f "$K/pending" ]; then st=pending
  elif failed_here; then st=failed
  elif [ "$(free_mb)" -lt "$(need_mb)" ]; then st=no_space
  elif onroad; then st=onroad
  fi
  echo "state=$st"
  echo "slot=$cur"
  echo "target=$oth"
  echo "agnos=$(agnos)"
  echo "image_agnos=$BOOT_AGNOS"
  echo "sha=$BOOT_SHA"
  echo "image=$(image_state)"
  echo "free_mb=$(free_mb)"
  echo "need_mb=$(need_mb)"
  if [ -f "$K/ok" ]; then echo "last=ok"; elif [ -f "$K/failed" ]; then echo "last=failed"; fi
  return 0
}

fetch() {
  [ "$(image_state)" = ok ] && { echo "boot.img already matches"; return 0; }
  mkdir -p "$DIR"
  rm -f "$IMG" "$IMG.sha256"
  # resume a partial download; nothing is flashed until the sha matches
  $CURL -fL --retry 5 --retry-delay 3 -C - -o "$IMG.part" "$BOOT_URL" || die "download failed: $BOOT_URL"
  [ "$(stat -c %s "$IMG.part")" = "$BOOT_SIZE" ] || { rm -f "$IMG.part"; die "downloaded boot.img has the wrong size"; }
  [ "$(fsha "$IMG.part")" = "$BOOT_SHA" ] || { rm -f "$IMG.part"; die "downloaded boot.img does not match the pinned sha"; }
  mv "$IMG.part" "$IMG"
  echo "$BOOT_SHA  boot.img" > "$IMG.sha256"
  echo "boot.img ok"
}

# keep the newest $KEEP old backups on /data; the live one is never touched
prune() {
  local old n=0
  while read -r old; do
    n=$((n + 1))
    if [ "$n" -gt "$KEEP" ]; then run rm -rf "$old"; fi
  done < <(ls -1dt "$DIR"/backup.* 2> /dev/null || true)
}

flash() {
  local a retry=0
  for a in "$@"; do
    case $a in
      --yes) YES=1 ;;
      --retry) retry=1 ;;
      *) die "unknown flash arg $a" ;;
    esac
  done
  [ -e "$WCN" ] && die "the dpbridge kernel is already running"
  model_ok || die "not a comma 4 (mici)"
  [ "$(agnos)" = "$BOOT_AGNOS" ] || die "AGNOS $(agnos) but the image is for $BOOT_AGNOS"
  onroad && die "onroad, flash only when parked"
  [ $retry = 1 ] || ! failed_here || die "the last flash of this image on this slot failed, pass --retry"
  [ "$(free_mb)" -ge "$(need_mb)" ] || die "not enough space on /data, need $(need_mb) MB"
  if [ "$(image_state)" != ok ]; then
    if [ $YES = 1 ]; then fetch; else echo "+ download $BOOT_URL (sha $BOOT_SHA)"; echo "dry run: stops before the download"; return 0; fi
  fi
  local cur oth
  cur=$(abctl --boot_slot)
  oth=$(other "$cur")
  [ "$oth" != "$cur" ] || die "target is the running slot"
  echo "running $cur, writing $oth only"
  local fargs=(--rotate)
  [ $YES = 1 ] && fargs+=(--yes)
  mkdir -p "$K"
  if ! bash "$HERE/flash_boot.sh" "${fargs[@]}" "$IMG"; then
    # no automatic retry of the same thing; the slot was not switched
    [ $YES = 1 ] && try_key > "$K/failed"
    die "flash_boot.sh failed"
  fi
  prune
  [ $YES = 1 ] || { echo "dry run: no reboot"; return 0; }
  rm -f "$K/ok" "$K/failed"
  echo "$(try_key) $oth" > "$K/pending"
  sync
  echo "rebooting into $oth"
  $REBOOT
}

post_boot() {
  [ "${1:-}" = --yes ] && YES=1
  [ -f "$K/pending" ] || { echo "nothing pending"; return 0; }
  if [ -e "$WCN" ]; then
    run mv "$K/pending" "$K/ok"
    run bash "$HERE/install_userspace.sh" --yes
  else
    # the bootloader went back to the stock slot: key the failure so it is not retried in a loop
    if [ $YES = 1 ]; then cut -d' ' -f1-3 "$K/pending" > "$K/failed"; rm -f "$K/pending"; fi
    echo "dpbridge kernel did not boot, back on stock"
  fi
}

case ${1:-} in
  status) status ;;
  fetch) fetch ;;
  flash) shift; flash "$@" ;;
  post-boot) shift; post_boot "$@" ;;
  *) echo "usage: kernel.sh status|fetch|flash [--yes] [--retry]|post-boot [--yes]"; exit 2 ;;
esac
