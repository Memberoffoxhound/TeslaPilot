#!/usr/bin/env python3
# pull the bundled chestnut big model in one stream that resumes across reboots, then check it out
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
import lfs
from openpilot.selfdrive.modeld.accel_keys import BIG_MODEL as PKL


def partial(oid: str) -> Path:
  # matches accel_progress.bundled_download's {oid}-*/object
  return lfs.object_path(oid).parent / f'{oid}-resume' / 'object'


def fetch(oid: str, size: int, urlopen=urllib.request.urlopen) -> Path:
  dst, part = lfs.object_path(oid), partial(oid)
  with lfs.object_lock(oid):
    # lfs.py's temp dirs a reboot cut short; prune never removes them
    for d in dst.parent.glob(f'{oid}-*'):
      if d != part.parent:
        shutil.rmtree(d, ignore_errors=True)
    if lfs.valid(dst, size):
      return dst
    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.is_file() else 0
    if have > size:
      have = 0
    if have < size:
      req = lfs.hf_request(f"https://huggingface.co/buckets/{lfs.BUCKET}/resolve/sha256/{oid}")
      req.add_header('Range', f'bytes={have}-')
      with urlopen(req, timeout=30) as r:
        if r.status != 206:
          have = 0  # range ignored, start over
        with part.open('r+b' if have else 'wb') as out:
          out.seek(have)
          out.truncate()
          while chunk := r.read(1 << 20):
            out.write(chunk)
    if part.stat().st_size != size or lfs.hash_file(part) != oid:
      part.unlink()
      raise RuntimeError(f'big model {oid} incomplete or corrupt, starting over')
    os.replace(part, dst)
    part.parent.rmdir()
    return dst


def main() -> int:
  p = lfs.parse_pointer((ROOT / PKL).read_bytes()[:1024]) if (ROOT / PKL).is_file() else None
  if p is None:
    return 0
  fetch(*p)
  lfs.pull()  # checks it out like updated does
  return 0


if __name__ == '__main__':
  sys.exit(main())
