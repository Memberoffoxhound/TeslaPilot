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
| `kernel/*.patch` | build host | 6 patches on agnos-kernel-sdm845 e88ac80: config, DT (BT UART as ttyHS1), WCN3990 setup in btqca/hci_qca |
| `build_kernel.sh` | Linux | clones agnos-builder 140ed0c, applies the patches, builds and signs `boot.img` |
| `probe_ro.sh` | comma | read-only probe: kernel config, UART node, rfkill, BT partition, A/B sizes, audio |
| `flash_boot.sh` | comma | backs up both boot slots, mirrors the current slot to the other, writes `boot.img` to the other slot only, switches to it. Dry run unless `--yes` |
| `restore_boot.sh` | comma | switches back to the stock slot (`--write` also restores the boot backup) |
| `install_userspace.sh` | comma | BT firmware from the bluetooth partition, bluez, bluez-alsa, services. Dry run unless `--yes` |
| `attach.sh` | comma | started by `dpbridge-bt.service`: power on, `btattach` on /dev/ttyHS1 |
| `test_bt.sh` | both | the 16 acceptance checks; device rows skip without hci0 |
| `dk_unpack.py` | dev box | DashKit frames from a route as CSV, `--check` for the acceptance test |
| `mac/deliver.sh` | Mac | copies everything over SSH and runs the steps below |

openpilot side: `openpilot/system/dpbridge/` (dashkitd, btagentd, a2dp ducking), params `DashKitBridge`,
`DashKitAddr`, `DashKitVersion`, `DpbA2dpOnroad`, `DpbCmd`, `DpbStatus`, and Settings > bluetooth.
All of it stays off when `/sys/class/bluetooth/hci0` is missing.

## Steps

1. Build: `tools/dpbridge/build_kernel.sh` (prints the boot.img sha256).
2. Probe (read only): `mac/deliver.sh probe`. Check AGNOS 20.6 and that `bluetooth_a` MATCHes.
3. Copy: `mac/deliver.sh push`.
4. Dry run: `mac/deliver.sh flash`. Read the plan: it must write `boot_<other>` only.
5. Flash: `mac/deliver.sh flash --yes`. This also pulls the boot backups to `~/dpbridge-backup/<date>/`.
6. `mac/deliver.sh reboot`, wait a minute, then `mac/deliver.sh probe` again: kernel config shows BT, UART node `ok`.
7. Userspace: `mac/deliver.sh install`, then `mac/deliver.sh install --yes`, then `mac/deliver.sh reboot`.
8. Test: `mac/deliver.sh test`. Pair in Settings > bluetooth, then rerun for the manual rows.

## Recovery

From best to worst:

1. It boots and SSH works: `mac/deliver.sh restore --yes`, then `mac/deliver.sh reboot`. The stock slot was never written.
2. It does not boot: the bootloader should fall back to the stock slot after failed tries
   (not verified on a comma 4). Leave it powered for a few minutes.
3. QDL, keeps your data: side USB-C to the Mac first, then power on the top port (30 W or more).
   Then `bunx --bun commaai/qdl.js setactiveslot <stock slot>` and `bunx --bun commaai/qdl.js reset`.
   The stock slot is in `~/dpbridge-backup/<date>/stock_slot`. To put a boot backup back:
   `bunx --bun commaai/qdl.js flash boot_b ~/dpbridge-backup/<date>/boot_b.img`.
4. Full reflash, wipes data: https://flash.comma.ai in Chrome, same cabling as 3.
