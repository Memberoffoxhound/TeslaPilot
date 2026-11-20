# shellcheck shell=bash disable=SC2034
# shared by flash_boot.sh and restore_boot.sh (sourced; the caller sets YES)
DIR=${DPB_DIR:-/data/dpbridge}
P=${DPB_PARTS:-/dev/disk/by-partlabel}
SUDO=${SUDO-sudo}
B=$DIR/backup

die() { echo "refusing: $*" >&2; exit 1; }
# no network or the release is not there yet: 75 (EX_TEMPFAIL), boot.py retries without counting it
dl_fail() { echo "refusing: download failed: $*" >&2; exit 75; }
# firmware and BlueZ downloads: give up on a stalled link (under 1 kB/s for 60 s) or after 10 min per try
DL_OPTS=(-fL --retry 2 --retry-delay 3 --connect-timeout 20 --speed-limit 1024 --speed-time 60 --max-time 600 -C -)
# apt the same way: a stalled mirror fails instead of hanging
APT_OPTS=(-o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 -o Acquire::Retries=1)
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
# dd with live progress: "kernel: <step> <pct>%" from $2 to $3 as its bytes reach $4. dd's args are unchanged and
# its stderr goes to a file, not a pipe, so nothing can kill it mid-write
pdd() {
  local step=$1 from=$2 to=$3 total=$4 log rep rc=0
  shift 4
  echo "+ $*"
  [ "$YES" = 1 ] || return 0
  log=$(mktemp)
  pct() { tr '\r' '\n' < "$log" | awk -v f="$from" -v t="$to" -v n="$total" '/^[0-9]+ bytes/ {b = $1} END {p = f + int(b * (t - f) / n); print (p > t ? t : p)}'; }
  (last=$from; while sleep 1; do p=$(pct); [ "$p" = "$last" ] || progress "$step" "$p"; last=$p; done) &
  rep=$!
  "$@" status=progress 2> "$log" || rc=$?
  kill -9 $rep 2> /dev/null || true
  wait $rep 2> /dev/null || true
  if [ $rc = 0 ]; then progress "$step" "$to"; else tr '\r' '\n' < "$log" | grep -v '^[0-9]* bytes' >&2 || true; fi
  rm -f "$log"
  return $rc
}
other() { case $1 in _a) echo _b ;; _b) echo _a ;; *) die "unknown slot '$1'" ;; esac; }

# kernel_warning.txt as plain text: titles on their own line, card text indented under them or as "- " lines
warning_text() {
  awk '/^#/ || /^icon:/ {next} /^title:/ {sub(/^title: */, ""); gsub(/\\n/, " "); print; t=1; next}
       NF {print (t ? "  " : "- ") $0; next} {t=0}' "$1"
}
