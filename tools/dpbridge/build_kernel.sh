#!/usr/bin/env bash
# Build a signed mici boot.img with the dpbridge Bluetooth patches.
# Linux host, no device needed. Output: $OUT/boot.img and boot.img.sha256
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
AGNOS_REF=140ed0cc395bc63144d2a8a9eaf13c397ec23672  # AGNOS 20.6
KERNEL_REF=e88ac80cc893f8d1808be58affdfc8c638e6b898
TC_SHA=d2451496fa23bbf94b8fc50a4b07a053ddffa70b1a7940d7b880eda0937187f7
WORK=${WORK:-$HOME/dpbridge-kernel}
AGNOS=${AGNOS:-$WORK/agnos-builder}
OUT=${OUT:-$WORK/out}
CMDLINE='console=ttyMSM0,115200n8 isolcpus=6,7 quiet loglevel=3 earlycon=msm_geni_serial,0xA84000 androidboot.hardware=qcom androidboot.console=ttyMSM0 ehci-hcd.park=3 lpm_levels.sleep_disabled=1 service_locator.enable=1 androidboot.selinux=permissive firmware_class.path=/firmware/image net.ifnames=0 dyndbg=""'
G="git -c user.name=dpbridge -c user.email=dpbridge@localhost"

for t in git make gcc bc flex bison openssl python3 curl; do
  command -v $t >/dev/null || { echo "missing: $t"; exit 1; }
done
mkdir -p "$WORK" "$OUT"

if [ ! -d "$AGNOS/.git" ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone -q https://github.com/commaai/agnos-builder "$AGNOS"
fi
cd "$AGNOS"
GIT_LFS_SKIP_SMUDGE=1 git -c advice.detachedHead=false checkout -q $AGNOS_REF
git submodule update -q --init agnos-kernel-sdm845
K=$AGNOS/agnos-kernel-sdm845

# fresh branch from the stock kernel every run so patches never stack
cd "$K"
git checkout -q -B dpbridge $KERNEL_REF
$G am -q "$HERE"/kernel/*.patch

case $(uname -m) in
  aarch64|arm64) T= ;;
  *)
    TC=$WORK/aarch64-linux-gnu-gcc
    if [ ! -x "$TC/bin/aarch64-linux-gnu-gcc" ]; then
      curl -fL -o "$WORK/tc.tgz" https://media.githubusercontent.com/media/commaai/agnos-builder/$AGNOS_REF/tools/aarch64-linux-gnu-gcc.tar.gz
      echo "$TC_SHA  $WORK/tc.tgz" | sha256sum -c -
      tar -xzf "$WORK/tc.tgz" -C "$WORK"
    fi
    T=$TC/bin/aarch64-linux-gnu-
    ;;
esac

# CC and LD set explicitly: the tree's gcc-wrapper.py needs python2
export ARCH=arm64 CROSS_COMPILE=$T KCFLAGS=-w KBUILD_BUILD_HOST=docker
make -s O=out tici_defconfig
make -j"$(nproc)" O=out CC="${T}gcc" LD="${T}ld.bfd" HOSTCFLAGS=-fcommon

# same image layout and signature as agnos-builder build_kernel.sh
cd "$OUT"
cp "$K/out/arch/arm64/boot/Image-dtb" .
python3 "$AGNOS/tools/mkbootimg" --kernel Image-dtb --ramdisk /dev/null --cmdline "$CMDLINE" \
  --pagesize 4096 --base 0x80000000 --kernel_offset 0x8000 --ramdisk_offset 0x8000 --tags_offset 0x100 \
  --output boot.img.nonsecure
openssl dgst -sha256 -binary boot.img.nonsecure > boot.img.digest
openssl pkeyutl -sign -in boot.img.digest -inkey "$AGNOS/vble-qti.key" -out boot.img.sig \
  -pkeyopt digest:sha256 -pkeyopt rsa_padding_mode:pkcs1
dd if=/dev/zero of=boot.img.sig.padded bs=2048 count=1 status=none
dd if=boot.img.sig of=boot.img.sig.padded conv=notrunc status=none
cat boot.img.nonsecure boot.img.sig.padded > boot.img
rm -f boot.img.nonsecure boot.img.digest boot.img.sig boot.img.sig.padded Image-dtb
sha256sum boot.img | tee boot.img.sha256
