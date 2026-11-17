# launch's resumable pull of the bundled big model (scripts/fetch_big_model.py)
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

from openpilot.common.basedir import BASEDIR

spec = importlib.util.spec_from_file_location('fetch_big_model', Path(BASEDIR) / 'scripts/fetch_big_model.py')
fbm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fbm)
DATA = bytes(range(256)) * 64
OID, SIZE = hashlib.sha256(DATA).hexdigest(), len(DATA)


class Resp(io.BytesIO):
  def __init__(self, body, status):
    super().__init__(body)
    self.status = status


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setattr(fbm.lfs, 'STORE', tmp_path / 'lfs/objects')
  monkeypatch.setattr(fbm.lfs, 'GIT_DIR', tmp_path)
  return tmp_path


def server(data=DATA, honor_range=True, calls=None):
  def urlopen(req, timeout):
    start = int(req.get_header('Range').split('=')[1].rstrip('-'))
    if calls is not None:
      calls.append(start)
    return Resp(data[start:], 206) if honor_range else Resp(data, 200)
  return urlopen


def test_fresh_download(store):
  assert fbm.fetch(OID, SIZE, server()).read_bytes() == DATA
  assert not fbm.partial(OID).parent.exists()


def test_resumes_a_partial(store):
  fbm.partial(OID).parent.mkdir(parents=True)
  fbm.partial(OID).write_bytes(DATA[:5000])
  calls = []
  assert fbm.fetch(OID, SIZE, server(calls=calls)).read_bytes() == DATA
  assert calls == [5000]


def test_range_ignored_starts_over(store):
  fbm.partial(OID).parent.mkdir(parents=True)
  fbm.partial(OID).write_bytes(b'x' * 5000)
  assert fbm.fetch(OID, SIZE, server(honor_range=False)).read_bytes() == DATA


def test_corrupt_is_dropped(store):
  with pytest.raises(RuntimeError):
    fbm.fetch(OID, SIZE, server(data=b'y' * SIZE))
  assert not fbm.partial(OID).exists()
  assert not fbm.lfs.object_path(OID).exists()


def test_present_needs_no_network(store):
  dst = fbm.lfs.object_path(OID)
  dst.parent.mkdir(parents=True)
  dst.write_bytes(DATA)
  assert fbm.fetch(OID, SIZE, lambda *a, **k: pytest.fail('downloaded again')) == dst


def test_no_network_keeps_the_partial(store):
  fbm.partial(OID).parent.mkdir(parents=True)
  fbm.partial(OID).write_bytes(DATA[:100])
  def offline(req, timeout):
    raise OSError('no network')
  with pytest.raises(OSError):
    fbm.fetch(OID, SIZE, offline)
  assert fbm.partial(OID).read_bytes() == DATA[:100]


def test_disk_full_keeps_what_it_wrote(store, monkeypatch):
  class Full(Resp):
    def read(self, n=-1):
      raise OSError(28, 'No space left on device')
  with pytest.raises(OSError):
    fbm.fetch(OID, SIZE, lambda req, timeout: Full(b'', 206))
  assert fbm.partial(OID).exists()


def test_stale_lfs_temp_dirs_are_removed(store):
  stale = fbm.lfs.object_path(OID).parent / f'{OID}-abc123'
  stale.mkdir(parents=True)
  (stale / 'object').write_bytes(b'z' * 9000)
  fbm.fetch(OID, SIZE, server())
  assert not stale.exists()


def test_ui_reads_the_partial(store, tmp_path):
  from openpilot.selfdrive.ui.accel_progress import bundled_download
  pkl = tmp_path / 'big.pkl'
  pkl.write_bytes(f"version https://git-lfs.github.com/spec/v1\noid sha256:{OID}\nsize {SIZE}\n".encode())
  fbm.partial(OID).parent.mkdir(parents=True)
  fbm.partial(OID).write_bytes(DATA[:SIZE // 2])
  assert 0.4 < bundled_download(pkl, store) < 0.8


@pytest.mark.parametrize('dev,pulled', [(None, False), ('none', False), ('chestnut', True), ('jetlink-usb', True), ('jetlink-ios', True)])
def test_updates_skip_the_big_model_without_an_accelerator(dev, pulled):
  from openpilot.system.updated.updated import BIG_MODEL, lfs_exclude
  assert BIG_MODEL == fbm.PKL
  assert lfs_exclude({'AcceleratorDevice': dev}) == ([] if pulled else ['--exclude', BIG_MODEL])
