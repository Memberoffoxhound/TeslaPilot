#!/usr/bin/env bash
# dpbridge acceptance checks (spec table, 16 rows). Device rows run on the comma, box rows on a dev machine.
# Rows that need hci0 skip when it is missing. Exit code is 1 if any row FAILs.
# env: DPB_ROUTE=<route dir> for row 12, DPB_KOUT=<kernel out dir> for row 16
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
DIR=${DPB_DIR:-/data/dpbridge}
fails=0
PY=${PY:-python3}

say() { printf '%-6s %2s  %s\n' "$1" "$2" "$3"; [ "$1" = FAIL ] && fails=$((fails + 1)); return 0; }
check() { local n=$1 name=$2; shift 2; if "$@" > /dev/null 2>&1; then say PASS "$n" "$name"; else say FAIL "$n" "$name"; fi; }
on_device() { [ -f /AGNOS ] || [ -d /usr/comma ]; }
has_hci() { [ -e /sys/class/bluetooth/hci0 ]; }

kconfig() { local c; c=$(zcat /proc/config.gz); for k in BT BT_BREDR BT_HCIUART_QCA MSM_BT_POWER; do grep -qx "CONFIG_$k=y" <<< "$c" || return 1; done; }
uart_power() { [ -e /dev/ttyHS1 ] && grep -qx bt_power /sys/class/rfkill/rfkill*/name; }
# GPS must keep ttyHS0 (88c000); BT gets ttyHS1 (898000)
tty_map() { [[ $(readlink -f /sys/class/tty/ttyHS0/device) == *88c000* ]] && [[ $(readlink -f /sys/class/tty/ttyHS1/device) == *898000* ]]; }
gps_alive() {
  PYTHONPATH="${DPB_OPENPILOT:-/data/openpilot}" $PY -c "import openpilot.cereal.messaging as m
s = m.sub_sock('ubloxRaw', timeout=5000)
assert m.recv_one(s) is not None"
}
firmware() {
  local d; d=$(dmesg)
  (cd /lib/firmware/qca && sha256sum -c --quiet "$DIR/firmware.sha256") &&
    grep -q crbtfw21 <<< "$d" && grep -q crnv21 <<< "$d" && ! grep -qi "qca.*\(fail\|error\)" <<< "$d"
}
# the address attach.sh derives from the serial, so not the chip default 00:00:00:00:5A:AD shared by every unit
hci_up() {
  local i a; i=$(btmgmt info); a=$(bash "$HERE/attach.sh" --print-addr) || return 1
  grep -q "current settings:.*powered" <<< "$i" && grep -q "manufacturer 29" <<< "$i" && grep -q "addr $a " <<< "$i"
}
scan() { bluetoothctl --timeout 10 scan on | grep -q "NEW.*Device"; }
dashkit_seen() { bluetoothctl devices | grep -q DashKit; }
bonds() { ls "$DIR"/bluetooth/*/*/info > /dev/null 2>&1 && grep -lq LinkKey "$DIR"/bluetooth/*/*/info; }
a2dp_sink() { bluetoothctl show | grep -qi 0000110b; }
# soundd and A2DP share MultiMedia1 (pcm0p) through dmix; music has its own softvol control
a2dp_running() { bluealsa-cli list-pcms 2> /dev/null | grep -q a2dpsnk && amixer -c0 cget name='dpbridge A2DP Playback Volume'; }
soundd_ok() { pgrep -f selfdrive.ui.soundd && grep -q RUNNING /proc/asound/card0/pcm0p/sub0/status; }
dtb_ok() {
  local d; d=$(dtc -I dtb -O dts "${DPB_KOUT:?}/arch/arm64/boot/dts/qcom/comma_mici.dtb" 2> /dev/null)
  grep -q 'hsuart1 = "/soc/qcom,qup_uart@0x898000"' <<< "$d" && grep -q 'hsuart0 = "/soc/qcom,qup_uart@0x88c000"' <<< "$d" &&
    grep -A12 'qcom,qup_uart@0x898000 {' <<< "$d" | grep -q 'status = "ok"'
}
pytest_dpb() (
  cd "$ROOT" && PYTHONPATH=$ROOT $PY -m pytest -q -p no:cacheprovider "${@/#/openpilot/system/dpbridge/tests/}"
)

if on_device; then
  check 1 "kernel config" kconfig
  check 2 "BT UART ttyHS1 + rfkill bt_power" uart_power
  check 2 "GPS still on ttyHS0, BT on ttyHS1" tty_map
  if pgrep -f ubloxd.pigeond > /dev/null; then check 2 "GPS publishing ubloxRaw" gps_alive; else say MANUAL 2 "GPS runs onroad: ignition on, rerun"; fi
  check 3 "pinned firmware installed and downloaded" firmware
  if has_hci; then
    check 4 "hci0 powered, Qualcomm, real address" hci_up
    if ! scan; then say FAIL 5 "scan finds devices"; elif dashkit_seen; then say PASS 5 "scan finds DashKit"
    else say MANUAL 5 "scan works, DashKit not seen: is the car awake?"; fi
    if bonds; then say PASS 6 "a bond with LinkKey on /data"; else say MANUAL 6 "pair the phone in settings, reboot, rerun"; fi
    check 7 "A2DP sink UUID registered" a2dp_sink
    if a2dp_running; then say MANUAL 8 "A2DP PCM running, confirm you hear it"; else say MANUAL 8 "connect the phone and play music, rerun"; fi
    say MANUAL 9 "play music, trigger an alert: music drops, alert audible, music returns"
    check 10 "soundd stream running through dmix" soundd_ok
    check 11 "dashkitd --probe: version + 10 packets in 5 s" env PYTHONPATH="${DPB_OPENPILOT:-/data/openpilot}" "$PY" -m openpilot.system.dpbridge.dashkitd --probe
    if [ -n "${DPB_ROUTE:-}" ]; then
      check 12 "DashKit frames in the route" "$PY" "$HERE/dk_unpack.py" --check "$DPB_ROUTE"
    else say SKIP 12 "set DPB_ROUTE to a route dir"; fi
  else
    for n in 4 5 6 7 8 9 10 11 12; do say SKIP $n "no hci0"; done
  fi
  for n in 13 14 15 16; do say SKIP $n "box row"; done
else
  for n in 1 2 3 4 5 6 7 8 9 10 11 12; do say SKIP $n "device row"; done
  check 13 "dkwire parse and fuzz" pytest_dpb test_dkwire.py
  check 14 "dashkitd and btagentd with fakes" pytest_dpb test_dashkitd.py test_btagentd.py test_a2dp.py
  check 15 "bluetooth page renders" env PYTHONPATH="$ROOT" "$PY" "$ROOT/openpilot/selfdrive/ui/tests/dpbridge_bt_screenshot.py"
  if [ -n "${DPB_KOUT:-}" ]; then check 16 "dtb: BT UART ok as hsuart1, GPS hsuart0" dtb_ok
  else say SKIP 16 "set DPB_KOUT to the kernel out dir"; fi
fi

echo "$fails failed"
[ $fails = 0 ]
