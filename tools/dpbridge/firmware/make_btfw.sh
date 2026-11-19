#!/usr/bin/env bash
# Build the BT firmware release tarball: linux-firmware's WCN3990 rev 21 pair and its license, pinned and checked.
# comma's bluetooth.img is not in it; install_userspace.sh fetches that from agnos-builder itself.
# usage: make_btfw.sh <outdir>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(realpath -m "${1:?outdir}")
FW_COMMIT=f859d9fda9379205c9bcf2eab11fae68891085ee
FW_URL=https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain
FILES="crbtfw21.tlv crnv21.bin LICENSE.QualcommAtheros_ath10k"
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
for f in qca/crbtfw21.tlv qca/crnv21.bin LICENSE.QualcommAtheros_ath10k; do
  curl -fsSL -o "$W/${f#qca/}" "$FW_URL/$f?id=$FW_COMMIT"
done
# shellcheck disable=SC2086
(cd "$W" && grep -E " ($(echo $FILES | tr ' ' '|'))$" "$HERE/firmware.sha256" | sha256sum -c --quiet)
mkdir -p "$OUT"
# shellcheck disable=SC2086
tar --sort=name --mtime=@1735689600 --owner=0 --group=0 -C "$W" -cf "$OUT/dpbridge-btfw-1.tar" $FILES
(cd "$OUT" && sha256sum dpbridge-btfw-1.tar | tee dpbridge-btfw-1.tar.sha256)
