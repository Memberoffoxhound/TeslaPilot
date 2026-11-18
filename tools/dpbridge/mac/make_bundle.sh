#!/usr/bin/env bash
# Stage the Mac bundle: deliver.sh, HOWTO.md, the device scripts, BT firmware, boot.img, and a git bundle of the branch.
# usage: BOOT=path/to/boot.img make_bundle.sh [out_dir]
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
D=$(cd "$HERE/.." && pwd)
REPO=$(git -C "$D" rev-parse --show-toplevel)
OUT=${1:-/workspace/dpbridge-mac-bundle}
BASE=${BASE:-e9155c2a7}

[ ! -e "$OUT" ] || [ -f "$OUT/deliver.sh" ] || { echo "$OUT exists and is not a bundle, refusing"; exit 1; }
rm -rf "$OUT"
mkdir -p "$OUT/dpbridge"
cp "$HERE/deliver.sh" "$HERE/HOWTO.md" "$OUT/"
cp "$D"/*.sh "$D"/*.py "$D/README.md" "$D/asound.conf" "$OUT/dpbridge/"
if [ -n "${BOOT:-}" ]; then
  cp "$BOOT" "$OUT/boot.img"
  (cd "$OUT" && sha256sum boot.img > boot.img.sha256)
fi
# WCN3990 firmware, pinned to the last linux-firmware commit that touched it and checked against firmware.sha256
FW_COMMIT=f859d9fda9379205c9bcf2eab11fae68891085ee
FW_URL=https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain
mkdir -p "$OUT/dpbridge/firmware"
cp "$D/firmware/firmware.sha256" "$OUT/dpbridge/firmware/"
for f in qca/crbtfw21.tlv qca/crnv21.bin LICENSE.QualcommAtheros_ath10k; do
  curl -fsSL -o "$OUT/dpbridge/firmware/${f#qca/}" "$FW_URL/$f?id=$FW_COMMIT"
done
(cd "$OUT/dpbridge/firmware" && sha256sum -c --quiet firmware.sha256)
git -C "$REPO" bundle create -q "$OUT/dpbridge.bundle" "$BASE..dpbridge"
(cd "$OUT" && find . -type f | sort)
