#!/usr/bin/env bash
# Build BlueZ for AGNOS (Ubuntu 24.04 arm64) as three debs plus a tarball for the GitHub release.
# Run inside an arm64 noble root (a qemu chroot works). obexd with the BIP client and phonebook dummy,
# so it needs no Evolution libs. Build deps: libglib2.0 dbus-1 udev ical readline systemd asound2 -dev. Debs Depend on what AGNOS has, never udev.
# usage: build_bluez.sh <outdir> [version]
set -euo pipefail
OUT=$(realpath -m "${1:?outdir}")
VER=${2:-5.83}
REV=0dpb1
# kernel.org sha256sums.asc
declare -A SRC_SHA=(
  [5.83]=108522d909d220581399bfec93daab62035539ceef3dda3e79970785c63bd24c
  [5.79]=4164a5303a9f71c70f48c03ff60be34231b568d93a9ad5e79928d34e6aa0ea8a
)
TRIPLE=aarch64-linux-gnu
[ "$(uname -m)" = aarch64 ] || { echo "run in an arm64 root"; exit 1; }
grep -q 'VERSION_ID="24.04"' /etc/os-release || { echo "build on Ubuntu 24.04 so glibc matches AGNOS"; exit 1; }

W=${WORK:-/tmp/bluez-build}
# reproducible: fixed time for dpkg-deb and tar, build dir kept out of the binaries (build ids)
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1735689600} LC_ALL=C TZ=UTC
export CFLAGS="-O2 -g -ffile-prefix-map=$W=/build"
mkdir -p "$W" "$OUT"
cd "$W"
TAR=bluez-$VER.tar.xz
[ -f "$TAR" ] || curl -fsSLO "https://www.kernel.org/pub/linux/bluetooth/$TAR"
[ "$(sha256sum < "$TAR" | cut -d' ' -f1)" = "${SRC_SHA[$VER]}" ] || { echo "$TAR sha mismatch"; exit 1; }
rm -rf "bluez-$VER" dest
tar -xJf "$TAR"
cd "bluez-$VER"

./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var --libexecdir=/usr/libexec \
  --libdir=/usr/lib/$TRIPLE --with-systemdsystemunitdir=/usr/lib/systemd/system \
  --with-systemduserunitdir=/usr/lib/systemd/user --enable-library --enable-deprecated \
  --with-phonebook=dummy --disable-manpages --disable-cups --disable-mesh --disable-midi \
  --disable-nfc --disable-testing --disable-btpclient --disable-hid2hci --disable-sixaxis
make -j"$(nproc)"
make install DESTDIR="$W/dest"
# Ubuntu ships btmgmt too; attach.sh uses it for the address
install -m 0755 tools/btmgmt "$W/dest/usr/bin/btmgmt"
cd "$W"

D=$W/dest
# only obexd should need these, and it must not
if readelf -d "$D/usr/libexec/bluetooth/obexd" | grep -qE 'libebook|libedataserver|libphone'; then
  echo "obexd links Evolution libs"; exit 1
fi

# split like Ubuntu: libbluetooth3, bluez-obexd, bluez (the rest, minus the -dev files)
pkg() { rm -rf "$W/p/$1"; mkdir -p "$W/p/$1/DEBIAN"; }
move() { local p=$1; shift; for f; do mkdir -p "$W/p/$p/$(dirname "$f")"; mv "$D/$f" "$W/p/$p/$f"; done; }
L=usr/lib/$TRIPLE
pkg libbluetooth3; pkg bluez-obexd; pkg bluez
rm -rf "$D/usr/include" "$D/$L/pkgconfig" "$D/$L"/libbluetooth.so "$D/$L"/*.la "$D/$L"/bluetooth/plugins/*.la
# shellcheck disable=SC2046
move libbluetooth3 $(cd "$D" && ls $L/libbluetooth.so.3*)
move bluez-obexd usr/libexec/bluetooth/obexd usr/lib/systemd/user/obex.service \
  usr/share/dbus-1/services/org.bluez.obex.service
# system bus policy: dpbridge runs obexd -s as root
for c in etc/dbus-1/system.d/obex.conf usr/share/dbus-1/system.d/obex.conf; do [ -e "$D/$c" ] && move bluez-obexd "$c"; done
[ -L "$D/usr/lib/systemd/user/dbus-org.bluez.obex.service" ] && move bluez-obexd usr/lib/systemd/user/dbus-org.bluez.obex.service
# make install leaves main.conf out; ship the upstream defaults like Ubuntu
mkdir -p "$D/etc/bluetooth"
for c in main input network; do
  f=bluez-$VER/src/$c.conf; [ -f "$f" ] || f=bluez-$VER/profiles/$c/$c.conf
  [ -f "$f" ] && install -m 0644 "$f" "$D/etc/bluetooth/$c.conf"
done
(cd "$D" && tar -cf - .) | (cd "$W/p/bluez" && tar -xf -)
find "$W/p" -type f -exec sh -c 'file -b "$1" | grep -q ELF && strip --strip-unneeded "$1"' _ {} \;

control() {
  local p=$1 deps=$2 desc=$3
  cat > "$W/p/$p/DEBIAN/control" <<CTL
Package: $p
Version: $VER-$REV
Architecture: arm64
Maintainer: dpbridge <noreply@users.noreply.github.com>
Depends: $deps
Section: admin
Priority: optional
Installed-Size: $(du -sk --exclude=DEBIAN "$W/p/$p" | cut -f1)
Description: $desc
 BlueZ $VER built by dpbridge for AGNOS: experimental API on, obexd BIP client, no Evolution libs.
CTL
}
control libbluetooth3 "libc6 (>= 2.38)" "Bluetooth library"
control bluez-obexd "libc6 (>= 2.38), libdbus-1-3, libglib2.0-0t64, libical3t64, libsystemd0" "BlueZ OBEX daemon"
# only what the binaries link (readelf NEEDED) plus dbus and kmod
control bluez "libc6 (>= 2.38), libdbus-1-3, libglib2.0-0t64, libreadline8t64, kmod, dbus" "Bluetooth tools and daemons"
for p in bluez bluez-obexd; do
  [ -d "$W/p/$p/etc" ] && (cd "$W/p/$p" && find etc -type f | sort | sed 's#^#/#') > "$W/p/$p/DEBIAN/conffiles"
done

rm -f "$OUT"/*.deb
for p in libbluetooth3 bluez-obexd bluez; do
  # fixed mtimes and owner so the same tree gives the same deb
  find "$W/p/$p" -exec touch -h -d @"$SOURCE_DATE_EPOCH" {} +
  dpkg-deb --root-owner-group -Zxz --build "$W/p/$p" "$OUT/${p}_$VER-${REV}_arm64.deb" > /dev/null
done
NAME=dpbridge-bluez-$VER-arm64
(cd "$OUT" && sha256sum ./*.deb | sed 's# \./# #' > SHA256SUMS)
# shellcheck disable=SC2046,SC2012
tar --format=gnu --sort=name --numeric-owner --mtime=@"$SOURCE_DATE_EPOCH" --owner=0 --group=0 -C "$OUT" -cf "$OUT/$NAME.tar" \
  SHA256SUMS $(cd "$OUT" && ls ./*.deb | sed 's#\./##')
(cd "$OUT" && sha256sum "$NAME.tar" > "$NAME.tar.sha256")
cat "$OUT/$NAME.tar.sha256"
