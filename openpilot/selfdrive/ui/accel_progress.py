# accelerator icon progress: ('download', frac) or ('compile', None), else None
import math
from pathlib import Path

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.modeld.helpers import modeld_pkl_path

PERCENT_STAGES = ('download', 'upload')  # jetlink stages with a real fraction


def lfs_pointer(path: Path) -> tuple[str, int] | None:
  try:
    lines = path.read_bytes()[:300].decode().splitlines()
  except (OSError, UnicodeDecodeError):
    return None
  if not lines or not lines[0].startswith('version https://git-lfs'):
    return None
  kv = dict(ln.split(' ', 1) for ln in lines[1:] if ' ' in ln)
  try:
    return kv['oid'].removeprefix('sha256:'), int(kv['size'])
  except (KeyError, ValueError):
    return None


def bundled_download(pkl: Path | None = None, git_dir: Path | None = None) -> float | None:
  # how much of the bundled big model the launch pull has; None once it is checked out
  p = lfs_pointer(pkl or modeld_pkl_path(True))
  if p is None:
    return None
  oid, size = p
  d = (git_dir or Path(BASEDIR) / '.git') / 'lfs' / 'objects' / oid[:2] / oid[2:4]
  if (d / oid).is_file():
    return 1.0
  got = 0
  for part in d.glob(f'{oid}-*/object'):
    try:
      got = max(got, part.stat().st_blocks * 512)  # lfs.py preallocates a sparse file
    except OSError:
      pass
  return min(got / size, 1.0) if size > 0 else 0.0


def provisioning(mode: str, compile_progress, jetlink_progress, bundled: float | None):
  if mode == 'chestnut':
    if bundled is not None:
      return 'download', bundled
    stage = compile_progress.get('stage') if isinstance(compile_progress, dict) else None
    if stage == 'downloading':
      return 'download', _frac(compile_progress)
    return ('compile', None) if stage == 'compiling' else None
  if mode == 'jetlink' and isinstance(jetlink_progress, dict):
    stage = str(jetlink_progress.get('stage', ''))
    if stage in ('', 'ready', 'failed'):
      return None
    return ('download', _frac(jetlink_progress)) if stage in PERCENT_STAGES else ('compile', None)
  return None


def _frac(progress: dict) -> float:
  try:
    return max(0.0, min(1.0, float(progress.get('frac') or 0.0)))
  except (TypeError, ValueError):
    return 0.0


def pulse(t: float) -> float:
  return 0.35 + 0.65 * (0.5 - 0.5 * math.cos(t * 6.0))
