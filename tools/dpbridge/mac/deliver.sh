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
#   install      install_userspace.sh (dry run unless --yes; with --yes it shows the kernel warning, asks for a
#                typed yes, then runs detached from SSH with --accept-kernel, log in install.log)
#   attach       one manual chip bring-up for 20 s, output saved to ~/dpbridge-backup/<date>/attach.txt
#   enable       car off: start Bluetooth on every boot (after attach looked good); A2DP plays through soundd;
#                disable turns it off again
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
# kernel_warning.txt as plain text, as lib.sh prints it on the comma
warning_text() {
  awk '/^#/ || /^icon:/ {next} /^title:/ {sub(/^title: */, ""); gsub(/\\n/, " "); print; t=1; next}
       NF {print (t ? "  " : "- ") $0; next} {t=0}' "$1"
}
local_sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
remote_sha() { r "sha256sum $1" | cut -d' ' -f1; }
# / is read-only on AGNOS: open it for systemctl, always close it again, keep systemctl's rc
units() {
  echo "sudo mount -o remount,rw / && { sudo systemctl $1 --now $UNITS; rc=\$?; \
sudo mount -o remount,ro / || { echo 'warning: / is still rw until the next reboot'; }; exit \$rc; }"
}
UNITS="dpbridge-bt bluetooth bluealsa bluealsa-aplay"

reach() {
  [ -f "$KEY" ] || die "no SSH key at $KEY (use -i)"
  r true 2> /dev/null || die "cannot reach $HOST:$PORT with $KEY"
}

# run a device script detached, so a dropped SSH session can't stop it halfway; poll until <name>.rc appears.
# Stops waiting if the job is gone without one (reboot, power cut) or after DPB_<NAME>_MAX_S (default $4 s)
detached() {
  local name=$1 pat="[${2:0:1}]${2:1}" cmd=$3 v out end max last=""
  v="DPB_$(echo "$1" | tr '[:lower:]' '[:upper:]')_MAX_S"  # macOS bash 3.2: no ${x^^}
  max=${!v:-$4}
  r "pgrep -f $pat" > /dev/null && die "already running: $name"
  dev "rm -f $REMOTE/$name.rc; setsid nohup bash -c '$cmd > $REMOTE/$name.log 2>&1; \
    echo \$? > $REMOTE/$name.rc' < /dev/null > /dev/null 2>&1 &"
  end=$((SECONDS + max))
  while ! r "test -f $REMOTE/$name.rc" 2> /dev/null; do
    [ $SECONDS -lt $end ] || die "no result after $((max / 60)) min, see $REMOTE/$name.log"
    sleep "${DPB_POLL_S:-5}"
    if out=$(r "pgrep -f $pat > /dev/null || test -f $REMOTE/$name.rc || echo gone; tail -n 1 $REMOTE/$name.log" 2> /dev/null); then
      if grep -qx gone <<< "$out"; then
        # the script may have just exited with the wrapper's echo still to come
        sleep 2
        r "test -f $REMOTE/$name.rc" 2> /dev/null && break
        die "$name stopped without a result, see $REMOTE/$name.log (the slot switch is the last write)"
      fi
      echo "$out"
      last=$out
    else
      # the installer's own reboot: its last line, then no answer until the comma is back
      if grep -q 'kernel: rebooting 100%$' <<< "$last"; then echo "(rebooting into the new kernel)"; else echo "(no answer, still waiting)"; fi
    fi
  done
  r "cat $REMOTE/$name.log"
  [ "$(r "cat $REMOTE/$name.rc")" = 0 ] || die "$name failed, see above"
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
    for f in "$SRC"/*.sh "$SRC"/*.py "$SRC/asound.conf" "$SRC/kernel_warning.txt"; do push_file "$f"; done
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
        detached flash flash_boot.sh "bash $REMOTE/flash_boot.sh --yes" 3600
        backup_pull
        ;;
      *) dev "bash $REMOTE/flash_boot.sh" ;;
    esac
    ;;
  backup-pull) reach; backup_pull ;;
  install)
    reach
    case " $ARGS " in
      *" --yes "*)
        # the same warning as the comma's first-boot page; the kernel flashes only after a typed yes
        echo "This installs a custom kernel to enable Bluetooth."
        warning_text "$SRC/kernel_warning.txt"
        case " $ARGS " in
          *" --accept-kernel "*) ;;
          *)
            printf 'type yes to flash the kernel: '
            read -r ans || ans=""
            [ "$ans" = yes ] || die "not confirmed, nothing was run"
            ARGS="$ARGS --accept-kernel"
            ;;
        esac
        detached install install_userspace.sh "bash $REMOTE/install_userspace.sh $ARGS" 7200
        ;;
      *) dev "bash $REMOTE/install_userspace.sh $ARGS" ;;
    esac
    ;;
  attach)
    reach
    mkdir -p "$OUT"
    # if this hangs or SSH dies: reboot, nothing runs on its own at boot yet
    r "sudo timeout 20 $REMOTE/attach.sh & sleep 15; ls /sys/class/bluetooth; btmgmt info | head -5; \
      dmesg | grep -iE 'qca|bluetooth' | tail -20; dmesg | grep -i 'controller version'; ip -br addr show wlan0; wait" 2>&1 | tee "$OUT/attach.txt" || true
    # hci0 shows up even when setup failed, only a btmgmt controller means the chip came up
    n=$(sed -n 's/^Index list with \([0-9]*\) item.*/\1/p' "$OUT/attach.txt" | tail -1)
    if [ "${n:-0}" -ge 1 ]; then
      echo "saved $OUT/attach.txt. btmgmt lists $n controller(s): if wlan0 is UP, run enable"
    else
      echo "saved $OUT/attach.txt. chip did not respond, do not enable (btmgmt lists no controller)"
    fi
    ;;
  enable)
    reach
    dev "bash $REMOTE/audio.sh off"  # takes out the old dmix link if present; car off only
    r "rm -f $REMOTE/bt_off && $(units enable)"
    # systemctl can return 0 with failed starts, and a restart loop can look active, so each unit has to be
    # active and keep its restart count over 10 s
    if ! r "for _ in \$(seq 15); do systemctl is-active --quiet $UNITS && break; sleep 2; done; \
a=\$(systemctl show -p NRestarts --value $UNITS | paste -sd' '); sleep 10; \
b=\$(systemctl show -p NRestarts --value $UNITS | paste -sd' '); \
systemctl is-active --quiet $UNITS && [ \"\$a\" = \"\$b\" ] && exit 0; \
systemctl is-active $UNITS | paste -sd' '; echo \"restarts \$a -> \$b\"; exit 1"; then
      die "not all of $UNITS are active and stable, see journalctl -b -u dpbridge-bt -u bluetooth -u bluealsa -u bluealsa-aplay"
    fi
    echo "all active and stable: $UNITS"
    ;;
  disable)
    reach
    dev "bash $REMOTE/audio.sh off"
    r "touch $REMOTE/bt_off && $(units disable)"
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
