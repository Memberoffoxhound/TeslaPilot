# dpbridge from a Mac

Everything runs from this folder on the Mac. The comma is reached at `comma@192.168.68.67`
port 22 with `~/.ssh/comma_bruce_ed25519`. Override with `-h user@host`, `-p port`, `-i key`
before the command, for example `./deliver.sh -i ~/.ssh/other_key probe`.

Nothing writes to the comma's partitions until `./deliver.sh flash --yes`.
The current (stock) slot is never written; the new kernel goes to the other slot.

## Commands, in order

```sh
cd dpbridge-mac-bundle
shasum -a 256 -c boot.img.sha256        # boot.img: OK

./deliver.sh probe                       # read only, saved to ~/dpbridge-backup/<date>/probe.txt
                                         # check: AGNOS 20.6, bluetooth_a MATCH, every A/B pair has equal sizes
./deliver.sh push                        # boot.img + scripts to /data/dpbridge, sha256 checked on both ends
./deliver.sh flash                       # dry run: read the plan, it must write boot_<other> only
./deliver.sh flash --yes                 # backs up both boot slots, mirrors, flashes, switches slot,
                                         # then copies the backups to ~/dpbridge-backup/<date>/ and checks them
./deliver.sh reboot
./deliver.sh probe                       # now: CONFIG_BT=y, BT UART node status=ok, /dev/ttyHS1, rfkill bt_power

./deliver.sh install                     # dry run of the userspace install
./deliver.sh install --yes               # firmware, bluez, bluez-alsa, services
./deliver.sh reboot
./deliver.sh test                        # saved to ~/dpbridge-backup/<date>/test_bt.txt
```

Settings page and daemons need the dpbridge openpilot branch on the comma. The git bundle is
pushed with `push`. On the comma (it needs commit e9155c2a7 already):

```sh
ssh -i ~/.ssh/comma_bruce_ed25519 comma@192.168.68.67
cd /data/openpilot && git fetch /data/dpbridge/dpbridge.bundle dpbridge:dpbridge && git checkout dpbridge
sudo reboot
```

Then pair in Settings > bluetooth and run `./deliver.sh test` again for the manual rows.

## Going back

```sh
./deliver.sh restore                     # dry run
./deliver.sh restore --yes               # stock slot active again
./deliver.sh reboot
```

## Recovery with QDL (if it does not boot)

1. Give it a few minutes first: the bootloader should fall back to the stock slot after failed boots
   (not verified on a comma 4).
2. QDL mode: unplug everything. Connect the side USB-C port to the Mac first, then power the top port
   from a 30 W or stronger charger. The screen stays blank in QDL mode.
3. Install bun once: `curl -fsSL https://bun.sh/install | bash`
4. Switch back to the stock slot, keeping your data. The slot letter is in
   `~/dpbridge-backup/<date>/stock_slot` (`_a` means `a`):

   ```sh
   bunx --bun commaai/qdl.js getactiveslot
   bunx --bun commaai/qdl.js setactiveslot a
   bunx --bun commaai/qdl.js reset
   ```

   To also put the original boot image back on the other slot:
   `bunx --bun commaai/qdl.js flash boot_b ~/dpbridge-backup/<date>/boot_b.img`
5. Last resort, wipes the device: https://flash.comma.ai in Chrome, same cabling as step 2.

qdl.js uses the comma 3/3X programmer by default. The comma 4 is the same SoC, but this is not
verified; flash.comma.ai picks the right one itself.
