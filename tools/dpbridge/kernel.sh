#!/usr/bin/env bash
# Kernel flash, run only by install_userspace.sh (openpilot is down). No menu: every check is here.
#   status              key=value lines (state=ok|outdated|off|offer|failed|pending|no_space|unsupported_*)
#   flash [--yes] [--retry]  inactive slot only, read back, switch; the installer reboots. /data/dpbridge/disable
#                       or a failed try for this image, AGNOS and slot stop it; --retry overrides
#   post-boot [--yes]   after the reboot: record whether the new kernel came up
set -euo pipefail
YES=0
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib.sh
source "$HERE/lib.sh"
# shellcheck source=firmware/kernel.env
source "${DPB_KERNEL_ENV:-$HERE/firmware/kernel.env}"
WCN=${DPB_WCN:-/sys/module/hci_uart/parameters/wcn3990}
BOOT_ID=${DPB_BOOT_ID:-/proc/sys/kernel/random/boot_id}
K=$DIR/kernel
IMG=$DIR/boot.img
KEEP=${DPB_KEEP_BACKUPS:-3}
CURL=${DPB_CURL:-curl}

model_ok() { grep -q mici < <(tr -d '\0' < "${DPB_MODEL:-/sys/firmware/devicetree/base/model}"); }
agnos() { tr -d '[:space:]' < "${DPB_VERSION:-/VERSION}"; }
image_state() {
  [ -f "$IMG" ] || { echo missing; return; }
  [ "$(stat -c %s "$IMG")" = "$BOOT_SIZE" ] && [ "$(fsha "$IMG")" = "$BOOT_SHA" ] && echo ok || echo bad
}
# what a failed try is keyed on; an AGNOS update changes the slot or version, so it tries again
try_key() { echo "$BOOT_SHA $(agnos) $(abctl --boot_slot)"; }
failed_here() { [ -f "$K/failed" ] && [ "$(cat "$K/failed")" = "$(try_key)" ]; }
is_off() { [ -e "$DIR/disable" ]; }
# a dpbridge kernel runs: is it this image? the running slot is only read, once per boot (cached)
running_state() {
  local cur id; cur=$(abctl --boot_slot); id=$(cat "$BOOT_ID")
  if [ ! -f "$K/running" ] || [ "$(cut -d' ' -f1 "$K/running")" != "$id" ]; then
    mkdir -p "$K"
    if [ "$(dsha "$P/boot$cur" "$BOOT_SIZE")" = "$BOOT_SHA" ]; then echo "$id ok" > "$K/running"; else echo "$id outdated" > "$K/running"; fi
  fi
  cut -d' ' -f2 "$K/running"
}
free_mb() { if [ -n "${DPB_FREE_MB:-}" ]; then echo "$DPB_FREE_MB"; else df -Pm "$DIR" | awk 'NR==2{print $4}'; fi; }
need_mb() {
  local cur img=$BOOT_SIZE; cur=$(abctl --boot_slot)
  [ "$(image_state)" = ok ] && img=0
  # image, two boot backups, 64 MB spare
  echo $(( (img + 2 * $(size "$P/boot$cur")) / 1048576 + 64 ))
}

status() {
  mkdir -p "$DIR"
  local st=offer
  if [ -e "$WCN" ]; then st=$(running_state)
  elif is_off; then st=off
  elif ! model_ok; then st=unsupported_device
  elif [ "$(agnos)" != "$BOOT_AGNOS" ]; then st=unsupported_agnos
  elif [ -f "$K/pending" ]; then st=pending
  elif failed_here; then st=failed
  elif [ "$(free_mb)" -lt "$(need_mb)" ]; then st=no_space
  fi
  echo "state=$st"
  echo "agnos=$(agnos)"
  echo "image_agnos=$BOOT_AGNOS"
  echo "sha=$BOOT_SHA"
  return 0
}

# download 0-40%, from the .part size; a line per 4%. Ends with this script ($$ is the script's pid)
watch_dl() {
  local s p last=-1
  while sleep 1 && kill -0 $$ 2> /dev/null; do
    s=$(stat -c %s "$IMG.part" 2> /dev/null || echo 0)
    p=$((s * 40 / BOOT_SIZE / 4 * 4))
    if [ "$p" != "$last" ]; then progress downloading "$p"; last=$p; fi
  done
}

fetch() {
  [ "$(image_state)" = ok ] && { echo "boot.img already matches"; return 0; }
  mkdir -p "$DIR"
  rm -f "$IMG" "$IMG.sha256"
  progress downloading 0
  local w
  watch_dl & w=$!
  # shellcheck disable=SC2064
  trap "kill $w 2> /dev/null || true" EXIT
  # resume a partial download; nothing is flashed until the sha matches
  # a stalled link gives up (under 1 kB/s for 60 s), the boot-time run waits for this step without a clock
  $CURL -fL --retry 5 --retry-delay 3 --connect-timeout 20 --speed-limit 1024 --speed-time 60 -C - -o "$IMG.part" "$BOOT_URL" || die "download failed: $BOOT_URL"
  kill "$w" 2> /dev/null || true
  wait "$w" 2> /dev/null || true
  trap - EXIT
  progress verifying 40
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
  [ -e "$WCN" ] && die "a dpbridge kernel is already running ($(running_state)); restore_boot.sh --yes and reboot first to change it"
  model_ok || die "not a comma 4 (mici)"
  [ "$(agnos)" = "$BOOT_AGNOS" ] || die "AGNOS $(agnos) but the image is for $BOOT_AGNOS"
  if [ $retry = 0 ]; then
    is_off && die "kernel flash is off ($DIR/disable), pass --reflash to install"
    failed_here && die "the last flash of this image on this slot failed, pass --reflash to install"
  fi
  [ "$(free_mb)" -ge "$(need_mb)" ] || die "not enough space on /data, need $(need_mb) MB"
  if [ "$(image_state)" != ok ]; then
    if [ $YES = 1 ]; then fetch; else echo "+ download $BOOT_URL (sha $BOOT_SHA)"; echo "dry run: stops before the download"; return 0; fi
  fi
  progress verifying 40
  local cur oth
  cur=$(abctl --boot_slot)
  oth=$(other "$cur")
  [ "$oth" != "$cur" ] || die "target is the running slot"
  echo "running $cur, writing $oth only"
  local fargs=(--rotate)
  if [ $YES = 1 ]; then
    fargs+=(--yes)
    mkdir -p "$K"
    rm -f "$K/ok" "$K/failed"
    # before any write: a power loss from here on is recorded as a failed try by post-boot
    echo "$(try_key) $oth" > "$K/pending"
    sync
  fi
  # never stopped half way (abctl rewrites GPT attributes); flash_boot.sh inherits the ignore
  trap '' INT TERM HUP
  if ! bash "$HERE/flash_boot.sh" "${fargs[@]}" "$IMG"; then
    # no automatic retry of the same thing; the slot was not switched
    if [ $YES = 1 ]; then try_key > "$K/failed"; rm -f "$K/pending"; fi
    die "flash_boot.sh failed"
  fi
  trap - INT TERM HUP
  prune
  [ $YES = 1 ] || { echo "dry run: nothing switched"; return 0; }
  sync
  echo "flashed $oth, reboot to use it"
}

post_boot() {
  [ "${1:-}" = --yes ] && YES=1
  [ -f "$K/pending" ] || { echo "nothing pending"; return 0; }
  if [ -e "$WCN" ]; then
    run mv "$K/pending" "$K/ok"
    echo "dpbridge kernel booted"
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
