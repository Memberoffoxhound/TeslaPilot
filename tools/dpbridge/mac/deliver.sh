#!/usr/bin/env bash
# Run from a Mac: copy dpbridge to the comma over SSH and drive the device scripts.
# macOS bash 3.2 compatible. Nothing flashes without "flash --yes".
#
# usage: deliver.sh [-i key] [-h user@host] [-p port] <command> [--yes] [--write]
#   probe        read-only probe, output saved to ~/dpbridge-backup/<date>/probe.txt
#   push         copy boot.img, BT firmware and the scripts to /data/dpbridge, check sha256 on both ends
#   qdl-check    read-only QDL test on the Mac: proves the rescue path works on this comma before any flash
#   flash        flash_boot.sh as a dry run; with --yes it flashes detached from SSH, then pulls the boot backups
#   backup-pull  copy /data/dpbridge/backup to ~/dpbridge-backup/<date>/ and check sha256
#   install      install_userspace.sh (dry run unless --yes), after rebooting into the new kernel
#   attach       one manual chip bring-up for 20 s, output saved to ~/dpbridge-backup/<date>/attach.txt
#   enable       offroad: share the speaker with A2DP and start Bluetooth on every boot (after attach looked good);
#                disable turns both off again (audio sharing only offroad)
#   restore      restore_boot.sh (dry run unless --yes; --write also rewrites the boot slot)
#   test         test_bt.sh, output saved to ~/dpbridge-backup/<date>/test_bt.txt
#   reboot       sudo reboot on the comma
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
HOST=${COMMA_HOST:-comma@192.168.68.67}  # this comma's LAN address, override with -h
PORT=${COMMA_PORT:-22}
KEY=${COMMA_KEY:-$HOME/.ssh/comma_ed25519}
REMOTE=${DPB_REMOTE:-/data/dpbridge}
OUT=$HOME/dpbridge-backup/$(date +%Y-%m-%d)
if [ -f "$HERE/dpbridge/flash_boot.sh" ]; then SRC=$HERE/dpbridge; else SRC=$(cd "$HERE/.." && pwd); fi
BOOT=${BOOT:-$HERE/boot.img}
FW=${DPB_FW:-$SRC/firmware}  # the files in firmware.sha256 (make_bundle.sh fetches them) and qca.sha256

while getopts "i:h:p:" o; do
  case $o in
    i) KEY=$OPTARG ;;
    h) HOST=$OPTARG ;;
    p) PORT=$OPTARG ;;
    *) sed -n '/^set /q;2,$p' "$0"; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
CMD=${1:-}
[ $# -gt 0 ] && shift
ARGS="${*:-}"

SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=15)
r() { ssh "${SSH_OPTS[@]}" -p "$PORT" "$HOST" "$@"; }
dev() { r "export DPB_DIR=$REMOTE; $*"; }  # a device script, told where it lives
put() { scp -q "${SSH_OPTS[@]}" -P "$PORT" "$@"; }
get() { scp -q "${SSH_OPTS[@]}" -P "$PORT" "$@"; }
die() { echo "error: $*" >&2; exit 1; }
local_sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
remote_sha() { r "sha256sum $1" | cut -d' ' -f1; }

reach() {
  [ -f "$KEY" ] || die "no SSH key at $KEY (use -i)"
  r true 2> /dev/null || die "cannot reach $HOST:$PORT with $KEY"
}

push_file() {
  put "$1" "$HOST:$REMOTE/"
  [ "$(local_sha "$1")" = "$(remote_sha "$REMOTE/$(basename "$1")")" ] || die "sha256 mismatch for $(basename "$1")"
  echo "ok $(basename "$1") $(local_sha "$1")"
}

backup_pull() {
  mkdir -p "$OUT"
  get "$HOST:$REMOTE/backup/boot_a.img" "$HOST:$REMOTE/backup/boot_b.img" "$HOST:$REMOTE/backup/SHA256SUMS" \
    "$HOST:$REMOTE/backup/stock_slot" "$OUT/"
  (cd "$OUT" && shasum -a 256 -c SHA256SUMS) || die "backup copies in $OUT do not match"
  echo "backups in $OUT (stock slot $(cat "$OUT/stock_slot"))"
}

case $CMD in
  probe)
    reach
    mkdir -p "$OUT"
    r "mkdir -p $REMOTE"
    push_file "$SRC/probe_ro.sh" > /dev/null
    r "bash $REMOTE/probe_ro.sh" 2>&1 | tee "$OUT/probe.txt"
    echo "saved $OUT/probe.txt"
    ;;
  push)
    reach
    [ -f "$BOOT" ] || die "no boot.img at $BOOT (set BOOT=...)"
    [ -f "$BOOT.sha256" ] || die "no $BOOT.sha256"
    [ "$(cut -d' ' -f1 "$BOOT.sha256")" = "$(local_sha "$BOOT")" ] || die "boot.img does not match boot.img.sha256"
    (cd "$FW" && shasum -a 256 -c firmware.sha256) > /dev/null 2>&1 || die "BT firmware in $FW missing or not the pinned files"
    r "mkdir -p $REMOTE"
    push_file "$BOOT"
    for f in firmware.sha256 qca.sha256 $(awk '{print $2}' "$FW/firmware.sha256"); do push_file "$FW/$f"; done
    push_file "$BOOT.sha256"
    for f in "$SRC"/*.sh "$SRC"/*.py "$SRC/asound.conf"; do push_file "$f"; done
    r "chmod +x $REMOTE/*.sh $REMOTE/*.py"
    if [ -f "$HERE/dpbridge.bundle" ]; then push_file "$HERE/dpbridge.bundle"; fi
    ;;
  qdl-check)
    # comma in QDL mode on this Mac, see HOWTO; reads the active slot, then reboots it normally
    command -v bunx > /dev/null || die "install bun first, see HOWTO"
    bunx --bun commaai/qdl.js getactiveslot
    bunx --bun commaai/qdl.js reset
    ;;
  flash)
    reach
    case " $ARGS " in
      *" --yes "*)
        # detached, so a dropped SSH session can't stop it halfway
        r "pgrep -f [f]lash_boot.sh" > /dev/null && die "a flash is already running"
        dev "rm -f $REMOTE/flash.rc; setsid nohup bash -c 'bash $REMOTE/flash_boot.sh --yes > $REMOTE/flash.log 2>&1; \
          echo \$? > $REMOTE/flash.rc' < /dev/null > /dev/null 2>&1 &"
        # until flash.rc appears; stop if the job is gone without one (reboot, power cut) or after an hour
        end=$((SECONDS + ${DPB_FLASH_MAX_S:-3600}))
        while ! r "test -f $REMOTE/flash.rc" 2> /dev/null; do
          [ $SECONDS -lt $end ] || die "no result after $(( ${DPB_FLASH_MAX_S:-3600} / 60 )) min, see $REMOTE/flash.log"
          sleep "${DPB_POLL_S:-5}"
          if out=$(r "pgrep -f [f]lash_boot.sh > /dev/null || test -f $REMOTE/flash.rc || echo gone; tail -n 1 $REMOTE/flash.log" 2> /dev/null); then
            if grep -qx gone <<< "$out"; then
              # flash_boot.sh may have just exited with the wrapper's echo still to come
              sleep 2
              r "test -f $REMOTE/flash.rc" 2> /dev/null && break
              die "flash stopped without a result, see $REMOTE/flash.log (the slot switch is its last step)"
            fi
            echo "$out"
          else
            echo "(no answer, still waiting)"
          fi
        done
        r "cat $REMOTE/flash.log"
        [ "$(r "cat $REMOTE/flash.rc")" = 0 ] || die "flash failed, see above"
        backup_pull
        ;;
      *) dev "bash $REMOTE/flash_boot.sh" ;;
    esac
    ;;
  backup-pull) reach; backup_pull ;;
  install) reach; dev "bash $REMOTE/install_userspace.sh $ARGS" ;;
  attach)
    reach
    mkdir -p "$OUT"
    # if this hangs or SSH dies: reboot, nothing runs on its own at boot yet
    r "sudo timeout 20 $REMOTE/attach.sh & sleep 15; ls /sys/class/bluetooth; btmgmt info | head -5; \
      dmesg | grep -iE 'qca|bluetooth' | tail -20; ip -br addr show wlan0; wait" 2>&1 | tee "$OUT/attach.txt" || true
    echo "saved $OUT/attach.txt. hci0 listed and wlan0 UP: run enable"
    ;;
  enable)
    reach
    dev "bash $REMOTE/audio.sh on"  # offroad only; soundd and micd pick it up when they next start
    r "rm -f $REMOTE/disable && sudo systemctl enable --now dpbridge-bt bluetooth bluealsa bluealsa-aplay"
    ;;
  disable)
    reach
    r "touch $REMOTE/disable && sudo systemctl disable --now dpbridge-bt bluetooth bluealsa bluealsa-aplay"
    dev "bash $REMOTE/audio.sh off"
    ;;
  restore) reach; dev "bash $REMOTE/restore_boot.sh $ARGS" ;;
  test)
    reach
    mkdir -p "$OUT"
    dev "bash $REMOTE/test_bt.sh" 2>&1 | tee "$OUT/test_bt.txt" || true
    echo "saved $OUT/test_bt.txt"
    ;;
  reboot) reach; r "sudo reboot" || true ;;
  *) sed -n '/^set /q;2,$p' "$0"; exit 2 ;;
esac
