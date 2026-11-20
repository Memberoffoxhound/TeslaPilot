import os
import textwrap

import pytest


class FakeParams:
  def __init__(self, *args, root=None, keys=None, defaults=None, **values):
    data = {}
    if args:
      if isinstance(args[0], dict) and len(args) == 1 and root is None:
        data = dict(args[0])
      elif len(args) == 1:
        root = args[0] if root is None else root
      else:
        root = args[0] if root is None else root
        if isinstance(args[1], dict):
          data = dict(args[1])
    data.update(values)
    self.store = dict(data)
    self.values = self.store
    self.d = self.store
    self.root = str(root) if root is not None else None
    self.keys = set(keys) if keys is not None else None
    self.defaults = dict(defaults or {})

  def check_key(self, key):
    if self.keys is not None and key not in self.keys:
      raise KeyError(key)
    return key

  def get(self, key, return_default=False, block=False):
    self.check_key(key)
    if key in self.store:
      return self.store[key]
    return self.defaults.get(key) if return_default else None

  def get_bool(self, key, block=False, return_default=False):
    val = self.get(key, return_default=return_default, block=block)
    return bool(val)

  def put(self, key, value, block=False):
    self.check_key(key)
    self.store[key] = value

  put_bool = put

  def remove(self, key):
    self.store.pop(key, None)

  def get_param_path(self, key=""):
    if self.root is None:
      return key
    return os.path.join(self.root, key) if key else str(self.root)

  def __getitem__(self, key):
    return self.store[key]

  def __setitem__(self, key, value):
    self.store[key] = value

  def __contains__(self, key):
    return key in self.store

  def __iter__(self):
    return iter(self.store)

  def keys(self):
    return self.store.keys()

  def items(self):
    return self.store.items()


def setup_params_root(tmp_path, monkeypatch):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
  monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)
  return tmp_path / "d"


@pytest.fixture
def params_root(tmp_path, monkeypatch):
  return setup_params_root(tmp_path, monkeypatch)


# stand-in Params for UI probe subprocesses that draw without libparams_c.so
PARAMS_PROBE_STUB = textwrap.dedent("""\
  m = types.ModuleType("openpilot.common.params")
  class Params:
    def __init__(self, *a, **k): pass
    def get_bool(self, *a, **k): return False
    def get(self, *a, **k): return None
    def __getattr__(self, n): return lambda *a, **k: None
  m.Params = Params
  sys.modules["openpilot.common.params"] = m
""")

