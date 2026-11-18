#!/usr/bin/env bash
# Run from a Mac: copy dpbridge to the comma over SSH and drive the device scripts.
# macOS bash 3.2 compatible. Nothing flashes without "flash --yes".
#
# usage: deliver.sh [-i key] [-h user@host] [-p port] <command> [--yes] [--write]
#   probe        read-only probe, output saved to ~/dpbridge-backup/<date>/probe.txt
#   push         copy boot.img and the scripts to /data/dpbridge, check sha256 on both ends
#   flash        flash_boot.sh as a dry run; with --yes it flashes, then pulls the boot backups
#   backup-pull  copy /data/dpbridge/backup to ~/dpbridge-backup/<date>/ and check sha256
#   install      install_userspace.sh (dry run unless --yes), after rebooting into the new kernel
#   restore      restore_boot.sh (dry run unless --yes; --write also rewrites the boot slot)
#   test         test_bt.sh, output saved to ~/dpbridge-backup/<date>/test_bt.txt
#   reboot       sudo reboot on the comma
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
HOST=${COMMA_HOST:-comma@192.168.68.67}
PORT=${COMMA_PORT:-22}
KEY=${COMMA_KEY:-$HOME/.ssh/comma_bruce_ed25519}
REMOTE=${DPB_REMOTE:-/data/dpbridge}
OUT=$HOME/dpbridge-backup/$(date +%Y-%m-%d)
if [ -f "$HERE/dpbridge/flash_boot.sh" ]; then SRC=$HERE/dpbridge; else SRC=$(cd "$HERE/.." && pwd); fi
BOOT=${BOOT:-$HERE/boot.img}

while getopts "i:h:p:" o; do
  case $o in
    i) KEY=$OPTARG ;;
    h) HOST=$OPTARG ;;
    p) PORT=$OPTARG ;;
    *) sed -n '2,16p' "$0"; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
CMD=${1:-}
[ $# -gt 0 ] && shift
ARGS="${*:-}"

SSH_OPTS="-i $KEY -o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=15"
r() { ssh $SSH_OPTS -p "$PORT" "$HOST" "$@"; }
put() { scp -q $SSH_OPTS -P "$PORT" "$@"; }
get() { scp -q $SSH_OPTS -P "$PORT" "$@"; }
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
    r "mkdir -p $REMOTE"
    push_file "$BOOT"
    if [ -f "$BOOT.sha256" ]; then push_file "$BOOT.sha256"; fi
    for f in "$SRC"/*.sh "$SRC"/*.py; do push_file "$f"; done
    r "chmod +x $REMOTE/*.sh $REMOTE/*.py"
    if [ -f "$HERE/dpbridge.bundle" ]; then push_file "$HERE/dpbridge.bundle"; fi
    ;;
  flash)
    reach
    case " $ARGS " in
      *" --yes "*) r "bash $REMOTE/flash_boot.sh --yes" && backup_pull ;;
      *) r "bash $REMOTE/flash_boot.sh" ;;
    esac
    ;;
  backup-pull) reach; backup_pull ;;
  install) reach; r "bash $REMOTE/install_userspace.sh $ARGS" ;;
  restore) reach; r "bash $REMOTE/restore_boot.sh $ARGS" ;;
  test)
    reach
    mkdir -p "$OUT"
    r "bash $REMOTE/test_bt.sh" 2>&1 | tee "$OUT/test_bt.txt" || true
    echo "saved $OUT/test_bt.txt"
    ;;
  reboot) reach; r "sudo reboot" || true ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
