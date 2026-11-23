import sys
import time
from pathlib import Path

from openpilot.common.hardware import AGNOS
from openpilot.common.hardware.usb import CHESTNUT_USB_PRODUCT, USB_DEVICES_PATH, is_chestnut_usb_id

MODELS_DIR = Path(__file__).resolve().parent / 'models'


def modeld_pkl_path(chestnut: bool):
  prefix = 'big_' if chestnut else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'

PLAIN_MAGIC = b'SPTGPLN1'

def is_plain(path) -> bool:
  # a sunnypilot/zoompilot prebuilt model (plain_jit.py), not a tinygrad pickle
  try:
    with open(path, 'rb') as f:
      return f.read(len(PLAIN_MAGIC)) == PLAIN_MAGIC
  except OSError:
    return False

def load_oob(path, chestnut=False):
  from tinygrad import Context
  device = 'USB+AMD:LLVM' if chestnut else 'QCOM' if AGNOS else 'METAL' if sys.platform == 'darwin' else 'CPU:LLVM'
  with Context(DEV=device):
    if is_plain(path):
      from openpilot.selfdrive.modeld.plain_jit import load_model
      return load_model(str(path))
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
  # the bundled big model is an LFS pointer unless pulled by hand; never load a placeholder
  return all(p.is_file() and not is_lfs_pointer(p) for p in (path, *warps))

def big_model_file() -> str | None:
  # the downloaded chestnut model (openpilot/sunnypilot/models), once its files are all here
  try:
    from openpilot.sunnypilot.models.helpers import big_model_file as active_file
    path = active_file()
  except Exception:
    return None
  return path if path and Path(path).is_file() and not is_lfs_pointer(Path(path)) else None


def chestnut_model_ready() -> bool:
  # a big model modeld can load on a chestnut: the downloaded pick or the pulled bundled one
  return big_model_file() is not None or chestnut_compiled()
