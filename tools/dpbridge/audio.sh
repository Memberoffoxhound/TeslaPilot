#!/usr/bin/env bash
# Turn the shared dmix for soundd and A2DP on or off by linking $DIR/asound.conf to /etc/asound.conf.
# Car off only: soundd and micd read it when they start, and a manager process killed while driving stays dead.
# usage: audio.sh on|off
set -euo pipefail
YES=1
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
ETC=${DPB_ETC:-/etc/asound.conf}
CONF=$DIR/asound.conf

case ${1:-} in on | off) ;; *) echo "usage: audio.sh on|off"; exit 2 ;; esac
ours() { [ -L "$ETC" ] && [ "$(readlink "$ETC")" = "$CONF" ]; }
if [ "$1" = on ]; then
  [ -f "$CONF" ] || die "no $CONF, run deliver.sh push"
  if ours; then echo "audio sharing already on"; exit 0; fi
  [ ! -e "$ETC" ] || die "$ETC exists and is not ours"
elif ! ours; then
  echo "audio sharing already off"; exit 0
fi
if pgrep -f '[s]elfdrive.ui.soundd|[s]ystem.micd' > /dev/null; then
  die "soundd or micd is running, turn the car off (or close driver view) and rerun"
fi

# the rootfs is read-only
rw() { if [ "$ETC" = /etc/asound.conf ]; then $SUDO mount -o remount,"$1" /; fi; }
rw rw
if [ "$1" = on ]; then $SUDO ln -sfn "$CONF" "$ETC"; else $SUDO rm -f "$ETC"; fi
rw ro || echo "note: / stays writable until the next reboot"
echo "audio sharing $1, soundd and micd use it from their next start"
