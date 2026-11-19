# shellcheck shell=bash disable=SC2034
# shared by flash_boot.sh and restore_boot.sh (sourced; the caller sets YES)
DIR=${DPB_DIR:-/data/dpbridge}
P=${DPB_PARTS:-/dev/disk/by-partlabel}
SUDO=${SUDO-sudo}
B=$DIR/backup

die() { echo "refusing: $*" >&2; exit 1; }
# no network or the release is not there yet: 75 (EX_TEMPFAIL), boot.py retries without counting it
dl_fail() { echo "refusing: download failed: $*" >&2; exit 75; }
run() { echo "+ $*"; if [ "$YES" = 1 ]; then "$@"; fi; }
size() { $SUDO blockdev --getsize64 "$1"; }
fsha() { sha256sum < "$1" | cut -d' ' -f1; }

# sha256 of the first $2 bytes, read with O_DIRECT so it comes from flash and not the page cache
dsha() {
  # head closes the pipe early so dd may die of SIGPIPE; a failed read still gives a wrong hash
  { $SUDO dd if="$1" bs=1M count=$((($2 + 1048575) / 1048576)) iflag=direct status=none || true; } |
    head -c "$2" | sha256sum | cut -d' ' -f1
}

# abctl --set_active exits 0 even when it fails; success is only its "boot lun" line
activate() {
  echo "+ abctl --set_active $1"
  [ "$YES" = 1 ] || return 0
  local out
  out=$($SUDO abctl --set_active "$1" 2>&1) || true
  grep -q "as boot lun" <<< "$out" || die "abctl --set_active $1 failed: $out"
}

slot_num() { case $1 in _a) echo 0 ;; _b) echo 1 ;; *) die "unknown slot '$1'" ;; esac; }
# kernel flash step and percent, one line each in the installer output
progress() { if [ "$YES" = 1 ]; then echo "  kernel: $1 $2%"; fi; }
other() { case $1 in _a) echo _b ;; _b) echo _a ;; *) die "unknown slot '$1'" ;; esac; }
