# Fake comma for the tool tests: partitions as plain files, fake abctl/blockdev, and a dd that can corrupt writes.
import hashlib
import os
import shutil
from pathlib import Path

import pytest

MB = 1 << 20
REAL_DD = shutil.which('dd')
MIRROR = ('xbl', 'xbl_config', 'abl', 'aop', 'devcfg', 'system')


@pytest.fixture
def dev(tmp_path):
  parts, data, bin_ = tmp_path / 'parts', tmp_path / 'data', tmp_path / 'bin'
  for d in (parts, data, bin_):
    d.mkdir()
  for name, size in (('boot', 4 * MB), *((n, MB) for n in MIRROR), ('modem', MB)):
    (parts / f'{name}_a').write_bytes(name.encode() + b'A' * (size - len(name)))
    (parts / f'{name}_b').write_bytes(b'old' + b'B' * (size - 3))
  (parts / 'userdata').write_bytes(b'u' * MB)
  log = tmp_path / 'ops.log'
  (bin_ / 'abctl').write_text(f"""#!/bin/sh
[ "$1" = --boot_slot ] && cat {tmp_path}/slot && exit 0
echo abctl "$@" >> {log}
[ -f {tmp_path}/abctl_broken ] && echo "abctl: missing partition xbl_b" && exit 0
echo "setting /dev/disk/by-partlabel/xbl_x lun as boot lun"
""")
  (bin_ / 'blockdev').write_text('#!/bin/sh\nstat -c %s "$2"\n')
  # logs every write; flips the first byte of a target matching $CORRUPT after writing it
  (bin_ / 'dd').write_text(f"""#!/bin/bash
{REAL_DD} "$@" || exit
for a; do
  case $a in
    of=*) echo "dd ${{a#of=}}" >> {log}
          [ -n "$CORRUPT" ] && [[ $a == *$CORRUPT ]] && printf X | {REAL_DD} "$a" conv=notrunc status=none ;;
    if=*) [[ " $* " == *" iflag=direct "* ]] && echo "direct ${{a#if=}}" >> {log} ;;
  esac
done
exit 0
""")
  for f in bin_.iterdir():
    f.chmod(0o755)
  (tmp_path / 'slot').write_text('_a\n')
  (tmp_path / 'model').write_bytes(b'comma mici\0')
  (tmp_path / 'VERSION').write_text('20.6\n')
  img = data / 'boot.img'
  img.write_bytes(b'ANDROID!' + os.urandom(MB))
  write_sha(img)
  env = dict(os.environ, PATH=f'{bin_}:{os.environ["PATH"]}', DPB_DIR=str(data), DPB_PARTS=str(parts), SUDO='',
             DPB_MODEL=str(tmp_path / 'model'), DPB_VERSION=str(tmp_path / 'VERSION'), DPB_BLK='-f',
             DPB_WCN=str(tmp_path / 'wcn3990'))
  return tmp_path, parts, data, img, env


def write_sha(img):
  Path(f'{img}.sha256').write_text(f'{hashlib.sha256(img.read_bytes()).hexdigest()}  boot.img\n')
