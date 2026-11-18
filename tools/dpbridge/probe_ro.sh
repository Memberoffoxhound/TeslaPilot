#!/usr/bin/env bash
# read-only BT probe for the comma 4: no writes, no rfkill changes, no module loads
s() { echo; echo "== $*"; }

s model; tr -d '\0' < /sys/firmware/devicetree/base/model; echo
s agnos; cat /VERSION 2>/dev/null; uname -r; abctl --boot_slot 2>/dev/null
s kernel config
zcat /proc/config.gz 2>/dev/null | grep -E "CONFIG_(BT|BT_BREDR|BT_LE|BT_HCIUART|BT_HCIUART_QCA|BT_QCA|MSM_BT_POWER|BTFM_SLIM)="
s bt uart node
for n in /proc/device-tree/soc/qcom,qup_uart@0x898000 /proc/device-tree/soc/qcom,qup_uart@898000; do
  [ -d "$n" ] && echo "$n status=$(tr -d '\0' < "$n"/status 2>/dev/null)"
done
s bt power node
find /proc/device-tree/ -maxdepth 3 -name 'bt_wcn3990*' 2>/dev/null | while read -r n; do
  echo "$n compatible=$(tr '\0' ' ' < "$n"/compatible) status=$(tr -d '\0' < "$n"/status 2>/dev/null)"
done
s ttys; ls -l /dev/ttyHS* /dev/ttyMSM* 2>/dev/null
s rfkill; for r in /sys/class/rfkill/rfkill*; do echo "$r $(cat "$r"/type) $(cat "$r"/name) soft=$(cat "$r"/soft) hard=$(cat "$r"/hard)"; done 2>/dev/null
s hci; ls /sys/class/bluetooth 2>/dev/null || echo none
s firmware files on rootfs; (cd /lib/firmware/qca 2>/dev/null && sha256sum crbtfw21.tlv crnv21.bin) || echo none
s "gpio 45-48, hint only"
sudo -n cat /sys/kernel/debug/gpio 2>/dev/null | grep -E "gpio(45|46|47|48)[^0-9]" || echo "no debugfs view"
s "A/B partitions flash_boot.sh writes"
sz() { echo $(( $(cat /sys/class/block/"$(basename "$(readlink -f "$1")")"/size) * 512 )); }
for n in xbl xbl_config abl aop devcfg boot system; do
  echo "$n a=$(sz /dev/disk/by-partlabel/${n}_a) b=$(sz /dev/disk/by-partlabel/${n}_b)"
done
s "kernel modules, they must still load on the new kernel"
find "/lib/modules/$(uname -r)" -name '*.ko' 2>/dev/null | grep . || echo none
s sound
aplay -l 2>/dev/null
amixer -D hw:0 controls 2>/dev/null | grep -E "SEC_MI2S_RX Audio Mixer MultiMedia[0-9]+'" | head
s userspace; for b in bluetoothd btattach bluetoothctl btmgmt bluealsad bluealsa bluealsa-aplay; do printf "%s: %s\n" $b "$(command -v $b || echo missing)"; done
s usb; cat /sys/bus/usb/devices/*/product 2>/dev/null
s "done"
