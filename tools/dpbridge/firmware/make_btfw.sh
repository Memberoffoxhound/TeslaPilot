#!/usr/bin/env bash
# Build the BT firmware release tarball: linux-firmware's WCN3990 rev 21 pair and its license, plus comma's
# bluetooth.img from agnos-builder, all checked against firmware.sha256. Reproducible: same bytes every run.
# usage: make_btfw.sh <outdir>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(realpath -m "${1:?outdir}")
FW_COMMIT=f859d9fda9379205c9bcf2eab11fae68891085ee
FW_URL=https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain
IMG_COMMIT=140ed0cc395bc63144d2a8a9eaf13c397ec23672
IMG_URL=https://media.githubusercontent.com/media/commaai/agnos-builder/$IMG_COMMIT/firmware/bluetooth.img
FILES="crbtfw21.tlv crnv21.bin LICENSE.QualcommAtheros_ath10k bluetooth.img"
TAR=dpbridge-btfw-2.tar
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
for f in qca/crbtfw21.tlv qca/crnv21.bin LICENSE.QualcommAtheros_ath10k; do
  curl -fsSL -o "$W/${f#qca/}" "$FW_URL/$f?id=$FW_COMMIT"
done
curl -fsSL -o "$W/bluetooth.img" "$IMG_URL"
# shellcheck disable=SC2086
(cd "$W" && grep -E " ($(echo $FILES | tr ' ' '|'))$" "$HERE/firmware.sha256" | sha256sum -c --quiet)
mkdir -p "$OUT"
chmod 0644 "$W"/*
# shellcheck disable=SC2086
tar --format=gnu --sort=name --mtime=@1735689600 --owner=0 --group=0 --numeric-owner -C "$W" -cf "$OUT/$TAR" $FILES
(cd "$OUT" && sha256sum "$TAR" | tee "$TAR.sha256")
