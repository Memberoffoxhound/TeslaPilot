import json
import subprocess
import sys
import time
from functools import cache
from pathlib import Path

from openpilot.common.hardware import AGNOS
from openpilot.common.hardware.usb import CHESTNUT_USB_PRODUCT, USB_DEVICES_PATH, is_chestnut_usb_id

MODELS_DIR = Path(__file__).resolve().parent / 'models'
CHESTNUT_DIR = Path('/data/models/chestnut')  # <ref>/driving_tinygrad.pkl, compiled on device
CHESTNUT_PICK = 'ChestnutModelPick'


def modeld_pkl_path(chestnut: bool):
  prefix = 'big_' if chestnut else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'

def load_oob(path, chestnut=False):
  from tinygrad import Context
  device = 'USB+AMD:LLVM' if chestnut else 'QCOM' if AGNOS else 'METAL' if sys.platform == 'darwin' else 'CPU:LLVM'
  with Context(DEV=device):
    from tinygrad_repo.examples.openpilot.helpers import load_pickle
    return load_pickle(path, out_of_band=True)

def chestnut_present() -> bool:
  for d in USB_DEVICES_PATH.glob("*"):
    try:
      usb_id = (int((d / "idVendor").read_text(), 16), int((d / "idProduct").read_text(), 16))
      product = (d / "product").read_text().strip()
      if is_chestnut_usb_id(*usb_id) and product == CHESTNUT_USB_PRODUCT:
        return True
    except Exception:
      pass
  return False

def wait_for_chestnut(timeout: float = 10.) -> None:
  # the cable is detected before chestnut enumerates
  st = time.monotonic()
  while not chestnut_present():
    if time.monotonic() - st > timeout:
      raise TimeoutError("chestnut did not enumerate")
    time.sleep(0.1)

LFS_POINTER = b'version https://git-lfs.github.com/spec/v1'

def is_lfs_pointer(path: Path) -> bool:
  try:
    with open(path, 'rb') as f:
      return f.read(len(LFS_POINTER)) == LFS_POINTER
  except OSError:
    return False

def chestnut_compiled() -> bool:
  path = modeld_pkl_path(chestnut=True)
  warps = [MODELS_DIR / f'big_driving_warp_{size}_tinygrad.pkl' for size in ('1344x760', '1928x1208')]
  # the big model is an LFS pointer until launch fetches it; never load a placeholder
  return all(p.is_file() and not is_lfs_pointer(p) for p in (path, *warps))


@cache
def tinygrad_ref() -> str:
  # a compiled pkl only loads on the tinygrad that built it
  try:
    root = Path(__file__).resolve().parents[3]
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD:tinygrad_repo'], text=True, stderr=subprocess.DEVNULL).strip()
  except Exception:
    return ''

def compiled_dir(ref: str) -> Path:
  return CHESTNUT_DIR / ref

def compiled_ready(ref: str) -> bool:
  d = compiled_dir(ref)
  try:
    return (d / 'driving_tinygrad.pkl').is_file() and (d / 'tinygrad_ref').read_text().strip() == tinygrad_ref() != ''
  except OSError:
    return False

def chestnut_pick(params) -> str | None:
  try:
    pick = params.get(CHESTNUT_PICK)
    pick = json.loads(pick) if isinstance(pick, (bytes, str)) else pick
  except Exception:
    return None
  ref = pick.get('ref') if isinstance(pick, dict) else pick
  return str(ref) if ref else None

def chestnut_pick_pkl(params) -> Path | None:
  ref = chestnut_pick(params)
  return compiled_dir(ref) / 'driving_tinygrad.pkl' if ref and compiled_ready(ref) else None
