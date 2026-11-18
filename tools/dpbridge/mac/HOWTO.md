# dpbridge from a Mac

Everything runs from this folder on the Mac. The comma is reached at `comma@192.168.68.67`
port 22 with `~/.ssh/comma_ed25519`. Pass your key and address with `-i key` and `-h user@host`
(and `-p port`) before the command, for example `./deliver.sh -i ~/.ssh/my_comma_key probe`.

Nothing writes to the comma's partitions until `./deliver.sh flash --yes`.
The current (stock) slot is never written; the new kernel goes to the other slot.

## Commands, in order

```sh
cd dpbridge-mac-bundle
shasum -a 256 -c boot.img.sha256        # boot.img: OK

./deliver.sh probe                       # read only, saved to ~/dpbridge-backup/<date>/probe.txt
                                         # check: comma mici, AGNOS 20.6, bluetooth_a MATCH, equal A/B sizes
./deliver.sh qdl-check                   # comma in QDL mode (see Recovery 2), must print the active slot,
                                         # then it reboots normally. Do not flash if this fails.
./deliver.sh push                        # boot.img + scripts to /data/dpbridge, sha256 checked on both ends
./deliver.sh flash                       # dry run: read the plan, it must write the other slot only
./deliver.sh flash --yes                 # runs detached on the comma and is polled: backs up both boot slots,
                                         # marks the other slot unbootable, mirrors, flashes, reads back, switches,
                                         # then copies the backups to ~/dpbridge-backup/<date>/ and checks them
./deliver.sh reboot
./deliver.sh probe                       # now: CONFIG_BT=y, BT UART node status=ok, /dev/ttyHS1, rfkill bt_power

./deliver.sh install                     # dry run of the userspace install
./deliver.sh install --yes               # firmware, bluez, bluez-alsa, services; nothing enabled yet
./deliver.sh attach                      # first chip bring-up by hand, 20 s. Hang or SSH lost: reboot,
                                         # nothing runs at boot yet. Saved to ~/dpbridge-backup/<date>/attach.txt
./deliver.sh enable                      # only if attach listed hci0 and wlan0 is still UP
./deliver.sh reboot
./deliver.sh test                        # saved to ~/dpbridge-backup/<date>/test_bt.txt
```

`./deliver.sh disable` (or `touch /data/dpbridge/disable` on the comma) keeps the chip off from the next boot.

Settings page and daemons need the dpbridge openpilot branch on the comma. The git bundle is
pushed with `push`. On the comma (it needs commit e9155c2a7 already):

```sh
ssh -i ~/.ssh/comma_ed25519 comma@192.168.68.67
cd /data/openpilot && rm -f prebuilt
git fetch /data/dpbridge/dpbridge.bundle dpbridge:dpbridge && git checkout dpbridge
sudo reboot
```

`rm -f prebuilt` makes openpilot rebuild on boot; without it the new settings keys are missing and the UI crashes.
The first boot takes several minutes while it builds.

Then pair in Settings > bluetooth and run `./deliver.sh test` again for the manual rows.

## Going back

```sh
./deliver.sh restore                     # dry run
./deliver.sh restore --yes               # stock slot active again
./deliver.sh reboot
```

## Recovery with QDL (if it does not boot)

`S` is the stock slot letter from `~/dpbridge-backup/<date>/stock_slot` (`_a` means `a`), `O` is the other one.

1. Give it a few minutes first: the bootloader should fall back to the stock slot after failed boots
   (not verified on a comma 4).
2. QDL mode: unplug everything. Connect the side USB-C port to the Mac first, then power the top port
   from a 30 W or stronger charger. The screen stays blank in QDL mode.
3. Install bun once: `curl -fsSL https://bun.sh/install | bash`
4. Switch back to the stock slot, keeping your data:

   ```sh
   bunx --bun commaai/qdl.js getactiveslot
   bunx --bun commaai/qdl.js setactiveslot S
   bunx --bun commaai/qdl.js reset
   ```

   To also put the stock kernel on the other slot:
   `bunx --bun commaai/qdl.js flash boot_O ~/dpbridge-backup/<date>/boot_S.img`
5. Last resort, wipes the device: https://flash.comma.ai in Chrome, same cabling as step 2.

qdl.js uses the comma 3/3X programmer by default. The comma 4 is the same SoC; `qdl-check` before
flashing is what proves it works on this unit. flash.comma.ai picks the right programmer itself.
