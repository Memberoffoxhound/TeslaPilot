#!/usr/bin/env bash
# Removes the old shared-dmix link /etc/asound.conf if it points at $DIR/asound.conf. A2DP no longer needs it:
# bluealsa-aplay writes a FIFO that soundd mixes. Car off only, soundd and micd read it when they start.
# usage: audio.sh off
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
ETC=${DPB_ETC:-/etc/asound.conf}
CONF=$DIR/asound.conf

case ${1:-} in off) ;; on) echo "audio.sh on is gone, soundd mixes A2DP itself" >&2; exit 2 ;; *) echo "usage: audio.sh off"; exit 2 ;; esac
ours() { [ -L "$ETC" ] && [ "$(readlink "$ETC")" = "$CONF" ]; }
if ! ours; then
  echo "no audio link"; exit 0
fi
if pgrep -f '[s]elfdrive.ui.soundd|[s]ystem.micd' > /dev/null; then
  die "soundd or micd is running, turn the car off (or close driver view) and rerun"
fi

# the rootfs is read-only
rw() { if [ "$ETC" = /etc/asound.conf ]; then $SUDO mount -o remount,"$1" /; fi; }
rw rw
$SUDO rm -f "$ETC"
rw ro || echo "note: / stays writable until the next reboot"
echo "audio link removed, soundd and micd use the stock config from their next start"
