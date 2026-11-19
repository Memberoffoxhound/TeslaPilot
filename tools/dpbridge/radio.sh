#!/usr/bin/env bash
# Root helper: start or stop the Bluetooth units from DpbBluetooth.
# Start and stop do not remount /. --watch loops; --once applies once.
set -euo pipefail
DIR="${DPBRIDGE_DIR:-/data/dpbridge}"
PARAM="${DPB_BLUETOOTH_PARAM:-/data/params/d/DpbBluetooth}"
HCI0="${DPB_HCI0:-/sys/class/bluetooth/hci0}"
UNITS="${DPB_UNITS:-dpbridge-bt bluetooth bluealsa bluealsa-aplay}"
SYSTEMCTL="${DPB_SYSTEMCTL:-systemctl}"
INSTALL="${DPB_INSTALL:-}"

seed_param() {
  if [ ! -e "$PARAM" ]; then
    if [ -e "$HCI0" ] && [ ! -e "$DIR/disable" ]; then
      mkdir -p "$(dirname "$PARAM")"
      printf '1' > "$PARAM"
    else
      mkdir -p "$(dirname "$PARAM")"
      printf '0' > "$PARAM"
    fi
  fi
}

want_on() {
  seed_param
  [ "$(tr -d '[:space:]' < "$PARAM" 2>/dev/null || true)" = 1 ]
}

rfkill_bt() {
  local r name
  for r in /sys/class/rfkill/rfkill*; do
    [ -e "$r/name" ] || continue
    name=$(cat "$r/name" 2>/dev/null || true)
    if [ "$name" = bt_power ]; then
      echo "$1" > "$r/soft" 2>/dev/null || true
    fi
  done
}

apply() {
  if want_on; then
    rm -f "$DIR/disable"
    if [ -n "$INSTALL" ] && [ -x "$INSTALL" ]; then
      if [ ! -e /usr/libexec/bluetooth/bluetoothd ]; then
        "$INSTALL" --yes || true
      fi
    fi
    rfkill_bt 0
    # start only; enable would remount / to write symlinks
    # shellcheck disable=SC2086
    $SYSTEMCTL start $UNITS || true
  else
    mkdir -p "$DIR"
    touch "$DIR/disable"
    # shellcheck disable=SC2086
    $SYSTEMCTL stop $UNITS || true
    rfkill_bt 1
  fi
}

once=0
[ "${1:-}" = --once ] && once=1
if [ "$once" = 1 ]; then
  apply
  exit 0
fi
# --watch (default)
prev=""
while true; do
  cur=$(tr -d '[:space:]' < "$PARAM" 2>/dev/null || echo missing)
  if [ "$cur" != "$prev" ]; then
    apply
    prev=$cur
  fi
  sleep 1
done
