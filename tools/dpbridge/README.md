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
| `kernel/*.patch` | build host | 12 patches on agnos-kernel-sdm845 e88ac80: config, DT (BT UART as ttyHS1), WCN3990 setup and address in btqca/hci_qca |
| `build_kernel.sh` | Linux | clones agnos-builder 140ed0c, applies the patches, builds and signs `boot.img` |
| `probe_ro.sh` | comma | read-only probe: kernel config, UART node, rfkill, firmware, A/B sizes, modules, audio |
| `flash_boot.sh` | comma | comma 4 on AGNOS 20.6 only. Backs up both boot slots, marks the other slot unbootable, mirrors the partitions AGNOS updates (xbl xbl_config abl aop devcfg system) into it, writes `boot.img` there, reads everything back from flash, switches to it. Dry run unless `--yes` |
| `restore_boot.sh` | comma | switches back to the stock slot (`--write` also puts the stock kernel on the other slot) |
| `install_userspace.sh` | comma | the installer: pinned BT firmware, the dpbridge BlueZ build (`bluez/bluez.env`), bluez-alsa from noble, all debs kept in `/data/dpbridge/debs` so an AGNOS update reinstalls offline (dpkg, skip udev, skip what is already installed), services incl. `dpbridge-obex` for cover art, then the kernel (`kernel.sh`) when the stock one runs and a reboot last. Leaves audio alone. Dry run unless `--yes` |
| `boot.py` | comma | run by `launch_chffrplus.sh` before manager: `install_userspace.sh --yes` once per setup change with comma's spinner, never blocks openpilot, reboots only after a flash |
| `bluez/build_bluez.sh` | noble arm64 root | BlueZ 5.83 as three debs plus a tarball: experimental API, obexd with the BIP client, no Evolution libs. The tarball is a release asset; its sha is in `bluez/bluez.env` |
| `kernel.sh` | comma | automatic kernel flash, run only by `install_userspace.sh` on a stock kernel: status, fetch `boot.img` from the release (sha in `firmware/kernel.env`), `flash_boot.sh --rotate` on the inactive slot only; `post-boot` records the result on the next install |
| `firmware/firmware.sha256` | both | sha256 of `qca/crbtfw21.tlv`, `qca/crnv21.bin` and its license from linux-firmware f859d9f, and of comma's `firmware/bluetooth.img` from agnos-builder 140ed0c; `mac/make_bundle.sh` and `make_btfw.sh` fetch and check them |
| `firmware/qca.sha256` | comma | the six files installed in `/lib/firmware/qca`: rev 21 from linux-firmware, revs 11 and 20 from `bluetooth.img`. btqca picks by the chip's revision. Fallback if linux-firmware's rev 21 misbehaves: comma's own rev 21 pair from the same image (crbtfw21.tlv 2a42859081393ca6a50a177773385eac4fcabb9f21fc1b78299ed35bf8a598c4, crnv21.bin 18cc38fff25a6a56bc163f1874184da93d90882dc047c9f0c534ed9888c543b3): add both names to `comma_fw` in install and swap the two hashes here |
| `firmware/make_btfw.sh`, `firmware/btfw.env` | dev box, comma | linux-firmware's rev 21 pair and license plus comma's `bluetooth.img` as one reproducible release tarball (sha in `btfw.env`). `install_userspace.sh` fetches it into `/data/dpbridge`, so a fresh device needs no Mac |
| `bluetooth.img` | comma | comma's file, shipped with no license file upstream, mirrored here pinned by sha |
| `audio.sh` | comma | `off` removes the old `/etc/asound.conf` link if present. Offroad only |
| `asound.conf` | comma | `dpb_a2dp` for bluealsa-aplay only: S16 mono 48 kHz into `/run/dpbridge/a2dp.fifo` |
| `lib.sh` | comma | helpers shared by the scripts above |
| `attach.sh` | comma | started by `dpbridge-bt.service`: power on, `btattach` on /dev/ttyHS1, then this unit's own address |
| `test_bt.sh` | both | the 16 acceptance checks; device rows skip without hci0 |
| `dk_unpack.py` | dev box | DashKit frames from a route as CSV, `--check` for the acceptance test |
| `mac/deliver.sh` | Mac | copies everything over SSH and runs the steps below |

openpilot side: `openpilot/system/dpbridge/` (dashkitd, btagentd, a2dp ducking, nowplaying), params `DashKitBridge`,
`DashKitAddr`, `DashKitVersion`, `DpbA2dpOnroad`, `DpbCmd`, `DpbStatus`, and Settings > bluetooth.
Now playing is a tmpfs JSON file plus a home / disengaged-onroad card; it is hidden when nothing is up.
All of it stays off when `/sys/class/bluetooth/hci0` is missing.

Audio: the mici sound card exposes one playback PCM (MultiMedia1) and the 4.9 kernel has no SysV IPC, so there is
no dmix. `bluealsa-aplay` plays to `dpb_a2dp` (its own `ALSA_CONFIG_PATH`), which writes a FIFO in
`/run/dpbridge`; soundd (`openpilot/selfdrive/ui/dpb_music.py`) mixes it under its own output and adds nothing
during any alert or the shutter, then fades back in over 1 s after 0.5 s. Music level: dB in
`/data/dpbridge/music_db` (default -12, read once a second, never louder than the alert volume). The global ALSA
config is untouched.

## Steps

The installer does everything, with openpilot down. After an install from comma's installer URL it runs by itself:
`launch_chffrplus.sh` calls `boot.py` after `agnos_init`, before manager, on a comma 4 only. `boot.py` runs
`install_userspace.sh --yes` with comma's spinner and a progress bar on screen, then writes a stamp
(`/data/dpbridge_boot/stamp`: sha256 of the installer scripts, the pin files, the AGNOS version and the boot slot), so
it runs again only when the code, a pin, AGNOS or the slot changes. It is skipped while `/data/dpbridge/disable`
exists. A failure or the 20 min timeout on steps 1-3 is logged to `/data/dpbridge_boot/log`, openpilot starts
anyway and the next boot tries again, up to 3 runs per setup (`rm /data/dpbridge_boot/fails` to retry). A failed
download (no network, exit 75) is not counted. The kernel step is never killed and openpilot waits for it: its
boot.img download gives up on a stalled link, after 20 min per try or 25 min in all (resumed next run), before any
write (output in `/data/dpbridge_boot/install.out`).
After a flash it reboots once, without a stamp; the next boot records the result.
Do the first run parked at home on Wi-Fi: openpilot is not available for the minutes it takes, then one reboot.

By hand: `install_userspace.sh --yes` on the comma, or `mac/deliver.sh install --yes` from a Mac, which runs it
detached from SSH (log in `install.log`) so a dropped session can't stop a flash. It refuses while openpilot runs
onroad (`./manager.py` running and `IsOffroad` not 1). It prints `[1/4]` to `[4/4]` and the kernel step as
`kernel: <step> <percent>%` (downloading, verifying, backing up, writing slot X, reading back, switching slot), then
`kernel: rebooting 100%` from the installer.

1. `[1/4]` records how the last flash went (`kernel.sh post-boot`).
2. `[2/4]` BT firmware from the pinned release tarball. `[3/4]` BlueZ, bluez-alsa and the units.
3. `[4/4]` apt teardown first (/ read-only again), then on a stock kernel: fetch `boot.img` (pinned sha), write the
   inactive slot only, read it back, switch slots. The reboot is the installer's final step. On the pinned dpbridge kernel nothing is flashed and there is no reboot.
4. After the reboot the Bluetooth toggle in Settings starts the radio. After an AGNOS update the next boot runs the
   installer again.

Without `--yes` it is a dry run. `kernel.sh status` prints `state=`: `ok` (pinned kernel runs), `outdated` (an older
dpbridge kernel runs: restore first), `offer` (stock, install flashes), `off` (`/data/dpbridge/disable`), `failed`
(the last try with this image, AGNOS and slot failed), `pending`, `no_space`, `unsupported_agnos`, `unsupported_device`.
`install_userspace.sh --yes --reflash` flashes despite `off` or `failed`; without it both leave the kernel alone.
`no_space` and `unsupported_*` are printed and skipped; the rest of the install still succeeds.

Manual path (development, new kernel builds): `build_kernel.sh`, `mac/deliver.sh probe`, `qdl-check`, `push`,
`flash` (dry run) then `flash --yes`, `reboot`, `install --yes`, `test`. Boot a new image by hand this way before
the installer may flash it anywhere.

Kill switch: `touch /data/dpbridge/disable` stops the first-boot run and any kernel flash (`--reflash` overrides).
Bluetooth off is a separate file: the Settings toggle and `mac/deliver.sh disable` (car off) write
`/data/dpbridge/bt_off`, which keeps the chip off from the next boot and nothing else.
A device that ran an earlier dpbridge build with Bluetooth toggled off: `rm /data/dpbridge/disable` once.
If two Bluetooth starts in a row never settle (hci0 up for 60 s), the next one switches Bluetooth off instead and
Settings shows `off: did not start twice` under the toggle until it is switched on again.

## Recovery

From best to worst. `S` is the stock slot letter from `~/dpbridge-backup/<date>/stock_slot` (`_a` means `a`),
`O` is the other one.

1. It boots and SSH works: `mac/deliver.sh restore --yes`, then `mac/deliver.sh reboot`. The stock slot was never written.
   To stay on stock, `touch /data/dpbridge/disable` before that reboot: the slot change makes `boot.py` run the
   installer at the next boot, and on a stock kernel it flashes dpbridge again (inactive slot only). Remove the
   file to let it install again.
2. It does not boot: the bootloader should fall back to the stock slot after failed tries
   (not verified on a comma 4). Leave it powered for a few minutes.
3. QDL, keeps your data: side USB-C to the Mac first, then power on the top port (30 W or more).
   Then `bunx --bun commaai/qdl.js setactiveslot S` and `bunx --bun commaai/qdl.js reset`.
   To also put the stock kernel on the other slot:
   `bunx --bun commaai/qdl.js flash boot_O ~/dpbridge-backup/<date>/boot_S.img`.
4. Full reflash, wipes data: https://flash.comma.ai in Chrome, same cabling as 3.
