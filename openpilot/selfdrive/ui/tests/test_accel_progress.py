import os

from openpilot.selfdrive.ui import accel_progress as ap

OID = 'b4' + 'a' * 62
SIZE = 1 << 20


def pointer(tmp_path):
  pkl = tmp_path / 'big.pkl'
  pkl.write_text(f'version https://git-lfs.github.com/spec/v1\noid sha256:{OID}\nsize {SIZE}\n')
  return pkl


def test_bundled_download_counts_written_blocks(tmp_path):
  pkl, git = pointer(tmp_path), tmp_path / 'git'
  assert ap.bundled_download(pkl, git) == 0.0
  part = git / 'lfs/objects' / OID[:2] / OID[2:4] / f'{OID}-x1' / 'object'
  part.parent.mkdir(parents=True)
  with open(part, 'wb') as f:
    f.truncate(SIZE)  # preallocated, nothing written
    f.seek(0)
    f.write(os.urandom(SIZE * 3 // 10))
  assert 0.25 < ap.bundled_download(pkl, git) < 0.35
  (part.parent.parent / OID).write_bytes(b'x')
  assert ap.bundled_download(pkl, git) == 1.0
  pkl.write_bytes(b'\x80real pickle')
  assert ap.bundled_download(pkl, git) is None


def test_provisioning():
  assert ap.provisioning('chestnut', None, None, 0.3) == ('download', 0.3)
  assert ap.provisioning('chestnut', {'stage': 'downloading', 'frac': 0.7}, None, None) == ('download', 0.7)
  assert ap.provisioning('chestnut', {'stage': 'compiling', 'frac': 0}, None, None) == ('compile', None)
  assert ap.provisioning('chestnut', {'stage': 'failed'}, None, None) is None
  assert ap.provisioning('jetlink', None, {'stage': 'download', 'frac': 0.5}, None) == ('download', 0.5)
  assert ap.provisioning('jetlink', None, {'stage': 'build', 'frac': 0.5}, None) == ('compile', None)
  assert ap.provisioning('jetlink', None, {'stage': 'ready'}, None) is None
  assert ap.provisioning('none', None, {'stage': 'download'}, 0.1) is None
