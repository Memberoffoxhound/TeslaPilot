import json
from unittest import mock

import pytest

from openpilot.selfdrive.modeld import helpers
from openpilot.selfdrive.modeld import modeld

REF = 'a' * 40


class FakeParams(dict):
  def get(self, key, block=False):
    return super().get(key)

  def put(self, key, value):
    self[key] = value


@pytest.fixture
def compiled(tmp_path, monkeypatch):
  monkeypatch.setattr(helpers, 'CHESTNUT_DIR', tmp_path)
  monkeypatch.setattr(helpers, 'tinygrad_ref', lambda: 'tg1')
  d = tmp_path / REF
  d.mkdir()
  (d / 'driving_tinygrad.pkl').write_bytes(b'x')
  (d / 'tinygrad_ref').write_text('tg1')
  return d


def test_pick_needs_our_tinygrad(compiled):
  p = FakeParams(ChestnutModelPick={'ref': REF})
  assert helpers.chestnut_pick_pkl(p) == compiled / 'driving_tinygrad.pkl'
  (compiled / 'tinygrad_ref').write_text('tg0')
  assert helpers.chestnut_pick_pkl(p) is None
  assert helpers.chestnut_pick(FakeParams(ChestnutModelPick=json.dumps({'ref': REF}))) == REF
  assert helpers.chestnut_pick_pkl(FakeParams()) is None


def test_loads_the_pick(compiled):
  state = mock.Mock()
  assert modeld.load_chestnut(FakeParams(ChestnutModelPick={'ref': REF}), 1, 2, state) is state.return_value
  assert state.call_args.args[3] == compiled / 'driving_tinygrad.pkl'


def test_failed_pick_falls_back_to_bundled(compiled):
  paths = []

  def state(w, h, chestnut, pkl):
    paths.append(pkl)
    if pkl is not None:
      raise RuntimeError('bad pkl')
    return mock.Mock()

  p = FakeParams(ChestnutModelPick={'ref': REF})
  assert modeld.load_chestnut(p, 1, 2, state) is not None
  assert paths == [compiled / 'driving_tinygrad.pkl', None] and p['ChestnutModelFailed'] == REF


def test_nothing_loads(compiled):
  state = mock.Mock(side_effect=RuntimeError('no gpu'))
  assert modeld.load_chestnut(FakeParams(), 1, 2, state) is None
  assert state.call_count == 1
