# dpbridge

Turns on the comma 4 Bluetooth (WCN3990) so TeslaPilot can log DashKit CAN frames over BLE
and play phone music (A2DP) on the comma speaker. Needs a custom AGNOS boot image.

**Flashing a custom kernel can brick the device. Recovery may need QDL mode and a full reflash
that wipes your data. Read "Recovery" before you start.**

DashKit is log only: frames go to `customReservedRawData0` in the rlog and nowhere else.
Nothing here talks to the car or changes panda safety.

## Files

| file | runs on | what |
|---|---|---|
| `kernel/*.patch` | build host | 9 patches on agnos-kernel-sdm845 e88ac80: config, DT (BT UART as ttyHS1), WCN3990 setup and address in btqca/hci_qca |
| `build_kernel.sh` | Linux | clones agnos-builder 140ed0c, applies the patches, builds and signs `boot.img` |
| `probe_ro.sh` | comma | read-only probe: kernel config, UART node, rfkill, firmware, A/B sizes, modules, audio |
| `flash_boot.sh` | comma | comma 4 on AGNOS 20.6 only. Backs up both boot slots, marks the other slot unbootable, mirrors the partitions AGNOS updates (xbl xbl_config abl aop devcfg system) into it, writes `boot.img` there, reads everything back from flash, switches to it. Dry run unless `--yes` |
| `restore_boot.sh` | comma | switches back to the stock slot (`--write` also puts the stock kernel on the other slot) |
| `install_userspace.sh` | comma | pinned BT firmware, bluez, bluez-alsa, services (installed, not enabled). Leaves audio alone. Dry run unless `--yes` |
| `firmware/firmware.sha256` | both | sha256 of `qca/crbtfw21.tlv`, `qca/crnv21.bin` and its license from linux-firmware f859d9f, and of comma's `firmware/bluetooth.img` from agnos-builder 140ed0c (not committed: that repo has no license file); `mac/make_bundle.sh` fetches and checks them |
| `firmware/qca.sha256` | comma | the six files installed in `/lib/firmware/qca`: rev 21 from linux-firmware, revs 11 and 20 from `bluetooth.img`. btqca picks by the chip's revision. Fallback if linux-firmware's rev 21 misbehaves: comma's own rev 21 pair from the same image (crbtfw21.tlv 2a42859081393ca6a50a177773385eac4fcabb9f21fc1b78299ed35bf8a598c4, crnv21.bin 18cc38fff25a6a56bc163f1874184da93d90882dc047c9f0c534ed9888c543b3): add both names to `comma_fw` in install and swap the two hashes here |
| `audio.sh` | comma | `on` links `asound.conf` to `/etc/asound.conf`, `off` removes the link. Offroad only |
| `asound.conf` | comma | shared dmix for soundd and music, capture unchanged |
| `lib.sh` | comma | helpers shared by the scripts above |
| `attach.sh` | comma | started by `dpbridge-bt.service`: power on, `btattach` on /dev/ttyHS1, then this unit's own address |
| `test_bt.sh` | both | the 16 acceptance checks; device rows skip without hci0 |
| `dk_unpack.py` | dev box | DashKit frames from a route as CSV, `--check` for the acceptance test |
| `mac/deliver.sh` | Mac | copies everything over SSH and runs the steps below |

openpilot side: `openpilot/system/dpbridge/` (dashkitd, btagentd, a2dp ducking), params `DashKitBridge`,
`DashKitAddr`, `DashKitVersion`, `DpbA2dpOnroad`, `DpbCmd`, `DpbStatus`, and Settings > bluetooth.
All of it stays off when `/sys/class/bluetooth/hci0` is missing.

Audio: the mici sound card exposes one playback PCM (MultiMedia1). `asound.conf` puts soundd's playback (the
default device) and `bluealsa-aplay` on one dmix; capture stays on sysdefault, so micd is unchanged. It lives in
`/data/dpbridge` and is only active while `mac/deliver.sh enable` has linked it to `/etc/asound.conf`
(`disable` removes the link). Both refuse to change the link while soundd or micd runs (a no-op is fine): the manager does not restart a process
it lost, so they pick the change up at their next start (car off, after a reboot or ignition cycle). Music alone passes a softvol control
(`dpbridge A2DP Playback Volume`), which dpb_a2dp sets to 100% (normal), 60% (about -20 dB, during alerts) or 0 (muted
onroad). Alerts never pass it. The link is on the dpbridge slot only, so the stock slot keeps plain soundd.

## Steps

1. Build: `tools/dpbridge/build_kernel.sh` (prints the boot.img sha256).
2. Probe (read only): `mac/deliver.sh probe`. Check `comma mici`, AGNOS 20.6, the `bt_wcn3990` node and equal A/B sizes.
3. Prove QDL works on this comma before anything is written: `mac/deliver.sh qdl-check` (cabling in Recovery 3).
4. Copy: `mac/deliver.sh push`. It refuses without a matching `boot.img.sha256`.
5. Dry run: `mac/deliver.sh flash`. Read the plan: it must write the other slot only.
6. Flash: `mac/deliver.sh flash --yes`. It runs detached on the comma, so a dropped SSH session can't stop it.
   It also pulls the boot backups to `~/dpbridge-backup/<date>/`.
7. `mac/deliver.sh reboot`, wait a minute, then `mac/deliver.sh probe` again: kernel config shows BT, UART node `ok`.
8. Userspace: `mac/deliver.sh install`, then `mac/deliver.sh install --yes`. Nothing starts on its own yet.
9. First chip bring-up by hand: `mac/deliver.sh attach`. If it hangs or SSH dies, reboot: nothing runs at boot.
   Only if hci0 came up and wlan0 is still UP: with the car off, `mac/deliver.sh enable`, then `mac/deliver.sh reboot`.
10. Test: `mac/deliver.sh test`. Pair in Settings > bluetooth, then rerun for the manual rows.

Kill switch: `touch /data/dpbridge/disable` keeps the chip off from the next boot. `mac/deliver.sh disable` (car off)
also stops the services and takes the audio link out.

## Recovery

From best to worst. `S` is the stock slot letter from `~/dpbridge-backup/<date>/stock_slot` (`_a` means `a`),
`O` is the other one.

1. It boots and SSH works: `mac/deliver.sh restore --yes`, then `mac/deliver.sh reboot`. The stock slot was never written.
2. It does not boot: the bootloader should fall back to the stock slot after failed tries
   (not verified on a comma 4). Leave it powered for a few minutes.
3. QDL, keeps your data: side USB-C to the Mac first, then power on the top port (30 W or more).
   Then `bunx --bun commaai/qdl.js setactiveslot S` and `bunx --bun commaai/qdl.js reset`.
   To also put the stock kernel on the other slot:
   `bunx --bun commaai/qdl.js flash boot_O ~/dpbridge-backup/<date>/boot_S.img`.
4. Full reflash, wipes data: https://flash.comma.ai in Chrome, same cabling as 3.
