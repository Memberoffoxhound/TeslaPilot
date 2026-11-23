# zoompilot's SPTGPLN1 loader on this tinygrad: build a small artifact on CPU and load it back
import pickle
import struct

import numpy as np
import pytest

from openpilot.selfdrive.modeld import plain_jit
from openpilot.selfdrive.modeld.tests.plain_artifact_compiler import capture_frame, record_kernel_linear, serialize_jit

DEV = 'CPU:LLVM'


def _inputs(x0=0.0):
  from tinygrad import Tensor
  return {'x': Tensor(np.arange(8, dtype=np.float32) + x0, device=DEV).realize(),
          'state': Tensor(np.ones(8, dtype=np.float32), device=DEV).realize(),
          'output_buffers': {'outputs': Tensor.zeros(1, 8, device=DEV).contiguous().realize(),
                             'next_state': Tensor.zeros(8, device=DEV).contiguous().realize()}}


def _run(x, state, output_buffers):
  from tinygrad import Tensor
  out = output_buffers['outputs'].assign((x * 2 + state).reshape(1, 8))
  nxt = output_buffers['next_state'].assign(state + 1)
  Tensor.realize(out, nxt)


@pytest.fixture(autouse=True)
def cpu():
  from tinygrad import Context
  with Context(DEV=DEV):
    yield


@pytest.fixture
def artifact(tmp_path):
  from tinygrad import TinyJit
  jit, inputs = TinyJit(_run, prune=True), _inputs()
  with record_kernel_linear() as recorded:
    jit(**inputs)
    jit(**inputs)
    check, _ = capture_frame(jit, inputs, 'output_buffers')
  part = serialize_jit(jit, recorded[0], check)
  path = tmp_path / 'model_tinygrad.pkl'
  extras = {'input_specs': {'x': ((8,), 'float32', DEV)}, 'metadata': {'output_shapes': {'outputs': (1, 8)}}}
  plain_jit.write_bundle(str(path), {'run': part}, extras)
  return path


def _outputs(jits, x0):
  inputs = _inputs(x0)
  jits['run'](**inputs)
  return inputs['output_buffers']['outputs'].numpy(), inputs['output_buffers']['next_state'].numpy()


def test_header_is_plain(artifact):
  data = artifact.read_bytes()
  assert data[:8] == plain_jit.MAGIC
  assert struct.unpack_from('<Q', data, 8)[0] > 0
  parts, extras = plain_jit.read_parts(str(artifact))
  assert list(parts) == ['run'] and extras['input_specs']['x'][0] == (8,)


def test_loads_and_runs_without_the_cache(artifact):
  jits = plain_jit.load_model(str(artifact), cache=False)
  assert set(jits) == {'run', 'input_specs', 'metadata'}
  out, nxt = _outputs(jits, 3.0)
  np.testing.assert_allclose(out[0], (np.arange(8) + 3.0) * 2 + 1)
  np.testing.assert_allclose(nxt, 2.0)


def test_boot_cache_is_written_and_reused(artifact):
  first = plain_jit.load_model(str(artifact))
  assert artifact.with_name(artifact.name + '.cache').is_file()
  assert plain_jit.cache_is_fresh(str(artifact))
  again = plain_jit.load_model(str(artifact))
  np.testing.assert_allclose(_outputs(first, 1.0)[0], _outputs(again, 1.0)[0])


def test_rejects_a_comma_pickle(tmp_path):
  path = tmp_path / 'driving_tinygrad.pkl'
  path.write_bytes(pickle.dumps({'run': None}))
  with pytest.raises(ValueError):
    plain_jit.read_parts(str(path))


def test_metadata_cannot_name_classes():
  with pytest.raises(pickle.UnpicklingError):
    plain_jit._MetadataUnpickler(__import__('io').BytesIO(pickle.dumps(np.float32(1)))).load()


def test_load_oob_reads_plain(artifact, monkeypatch):
  # modeld's loader takes a SPTGPLN1 file through plain_jit, a pickle through load_pickle
  from openpilot.selfdrive.modeld import helpers
  monkeypatch.setattr(helpers, 'AGNOS', False)
  assert helpers.is_plain(artifact)
  jits = helpers.load_oob(artifact)
  assert isinstance(jits['run'], plain_jit.PlainJit)
  assert jits['input_specs']['x'][0] == (8,)
  out, _ = _outputs(jits, 0.0)
  np.testing.assert_allclose(out, (np.arange(8) * 2 + 1).reshape(1, 8))


def test_is_plain_rejects_pickle(tmp_path):
  from openpilot.selfdrive.modeld import helpers
  path = tmp_path / 'x.pkl'
  path.write_bytes(pickle.dumps({'run': None}))
  assert not helpers.is_plain(path)
  assert not helpers.is_plain(tmp_path / 'missing.pkl')

def test_dtype_rejects_arbitrary_expressions():
  for bad in ("__import__('os')", "dtypes.f32.__class__", "float32", "dtypes.not_a_dtype"):
    with pytest.raises(ValueError):
      plain_jit._dtype(bad)


def test_cache_rejects_tampered_digest(artifact):
  plain_jit.load_model(str(artifact))
  cache_path = artifact.with_name(artifact.name + ".cache")
  raw = bytearray(cache_path.read_bytes())
  raw[-1] ^= 0xFF
  cache_path.write_bytes(bytes(raw))
  parts, _ = plain_jit.read_parts(str(artifact))
  assert plain_jit._read_cache(str(artifact), parts, None) is None


def test_cache_rejects_disallowed_class(artifact):
  import hashlib
  class Bad:
    def __reduce__(self):
      return (eval, ("1",))
  payload = pickle.dumps(Bad(), protocol=5)
  key = plain_jit._cache_key(str(artifact), None)
  artifact.with_name(artifact.name + ".cache").write_bytes(
    struct.pack("<Q", len(key)) + key + hashlib.sha256(payload).digest() + payload
  )
  parts, _ = plain_jit.read_parts(str(artifact))
  assert plain_jit._read_cache(str(artifact), parts, None) is None
