#!/usr/bin/env bash
# Stage the Mac bundle: deliver.sh, HOWTO.md, the device scripts, boot.img, and a git bundle of the branch.
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
cp "$D"/*.sh "$D"/*.py "$D/README.md" "$OUT/dpbridge/"
if [ -n "${BOOT:-}" ]; then
  cp "$BOOT" "$OUT/boot.img"
  (cd "$OUT" && sha256sum boot.img > boot.img.sha256)
fi
git -C "$REPO" bundle create -q "$OUT/dpbridge.bundle" "$BASE..dpbridge"
(cd "$OUT" && find . -type f | sort)
