# which big model modeld loads: the downloaded pick, then the bundled one, then the small model
from pathlib import Path

from openpilot.selfdrive.modeld import helpers, modeld


def test_big_model_file_needs_real_file(tmp_path, monkeypatch):
  import openpilot.sunnypilot.models.helpers as mh
  path = tmp_path / 'm.pkl'
  monkeypatch.setattr(mh, 'big_model_file', lambda *a, **k: str(path))
  assert helpers.big_model_file() is None
  path.write_bytes(helpers.LFS_POINTER + b' oid')
  assert helpers.big_model_file() is None
  path.write_bytes(b'SPTGPLN1')
  assert helpers.big_model_file() == str(path)


def test_big_model_file_no_pick(monkeypatch):
  import openpilot.sunnypilot.models.helpers as mh
  monkeypatch.setattr(mh, 'big_model_file', lambda *a, **k: None)
  assert helpers.big_model_file() is None


def test_order(monkeypatch):
  monkeypatch.setattr(modeld, 'big_model_file', lambda: '/data/media/0/models/a.pkl')
  monkeypatch.setattr(modeld, 'chestnut_compiled', lambda: True)
  assert modeld.chestnut_pkls() == ['/data/media/0/models/a.pkl', helpers.modeld_pkl_path(True)]
  monkeypatch.setattr(modeld, 'chestnut_compiled', lambda: False)
  assert modeld.chestnut_pkls() == ['/data/media/0/models/a.pkl']
  monkeypatch.setattr(modeld, 'big_model_file', lambda: None)
  assert modeld.chestnut_pkls() == []


class _State:
  def __init__(self, fail):
    self.fail, self.tried = fail, []

  def __call__(self, cam_w, cam_h, chestnut, pkl=None):
    self.tried.append(pkl)
    if pkl in self.fail:
      raise RuntimeError("bad model")
    state = self

    class M:
      path = pkl
      def warmup(self):
        state.tried.append('warm')
    return M()


def test_falls_back_to_bundled(monkeypatch):
  monkeypatch.setattr(modeld, 'chestnut_pkls', lambda: ['dl', 'bundled'])
  st = _State({'dl'})
  m = modeld.load_chestnut(None, 1928, 1208, st)
  assert m.path == 'bundled'
  assert st.tried == ['dl', 'bundled', 'warm']


def test_none_when_all_fail(monkeypatch):
  monkeypatch.setattr(modeld, 'chestnut_pkls', lambda: ['dl'])
  assert modeld.load_chestnut(None, 1928, 1208, _State({'dl'})) is None


def test_bundled_warps_are_real():
  # a downloaded model uses the bundled big warps, so they must never be LFS pointers
  for size in ('1344x760', '1928x1208'):
    p = Path(helpers.MODELS_DIR) / f'big_driving_warp_{size}_tinygrad.pkl'
    assert p.is_file() and not helpers.is_lfs_pointer(p)


def test_output_slices_rejects_disallowed_class(monkeypatch):
  import base64
  import pickle
  import pytest

  class Bad:
    def __reduce__(self):
      return (eval, ("1",))

  raw = base64.b64encode(pickle.dumps(Bad())).decode()
  jits = {
    "input_specs": {"new_img": ((1,), "float32", "CPU")},
    "metadata": {"output_shapes": {}, "metadata": {"output_slices": raw}},
    "output_specs": {},
    "run": None,
  }
  monkeypatch.setattr(modeld, "load_oob", lambda *a, **k: jits)
  with pytest.raises(pickle.UnpicklingError):
    modeld.ModelState(1928, 1208, False, pkl="unused")
