# the two big-model catalogs: sunnypilot's chestnut_v28 with a chestnut fitted, jetlink's index without
import json
import os
import tempfile
import time
from pathlib import Path
from typing import cast
from unittest import mock

from openpilot.common.params import Params
from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.models import default_bootstrap, fetcher_zp, manager as manager_module
from openpilot.sunnypilot.models.fetcher import ModelFetcher, ModelParser
from openpilot.sunnypilot.models.fetcher_zp import JETLINK_KEY, BigCatalogCache, ModelFetcherZP
from openpilot.sunnypilot.models.helpers import ACTIVE_BUNDLE_KEYS, REQUIRED_JSON_VERSION
from openpilot.sunnypilot.models.model_name import DEFAULT_BIG_MODEL, DEFAULT_BIG_MODEL_REF, DEFAULT_BIG_MODEL_SHA256

FIXTURES = Path(__file__).parent / "fixtures"


def chestnut_catalog() -> dict:
  return json.loads((FIXTURES / "chestnut_v28.json").read_text())


def jetlink_catalog() -> dict:
  # jetlink's Models.big_catalog over its v1 index
  from jetlink.registry.index import parse_index
  from jetlink.openpilot.models import Models
  index = parse_index(json.loads((FIXTURES / "jetlink_v1.json").read_text()))
  models = Models.__new__(Models)
  with mock.patch.object(Models, "refresh_index", return_value=index):
    return models.big_catalog(REQUIRED_JSON_VERSION)


def store(values=None) -> Params:
  return cast(Params, Store(values))


class Store:
  def __init__(self, values=None):
    self.values = dict(values or {})

  def get(self, key, *a, **k):
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.values.get(key))

  def put(self, key, value, *a, **k):
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


class TestSunnypilotCatalog(OpenpilotTestCase):
  def test_v28_parses(self):
    bundles = ModelParser.parse_models(chestnut_catalog())
    assert len(bundles) == 25
    assert all(b.minimumSelectorVersion == REQUIRED_JSON_VERSION for b in bundles)
    default = next(b for b in bundles if b.ref == DEFAULT_BIG_MODEL_REF)
    assert DEFAULT_BIG_MODEL in default.displayName
    names = [m.artifact.fileName for m in default.models]
    assert names == ["driving_light_speed_2_november_04_2026_tinygrad.pkl"]
    assert default.models[0].artifact.downloadUri.sha256 == DEFAULT_BIG_MODEL_SHA256

  def test_default_ref_rejects_sha256_mismatch(self):
    bad = chestnut_catalog()
    for bundle in bad["bundles"]:
      if bundle.get("ref") == DEFAULT_BIG_MODEL_REF:
        bundle["models"][0]["artifact"]["download_uri"]["sha256"] = "0" * 64
    with self.assertRaises(ValueError):
      ModelParser.parse_models(bad)

  def test_v28_is_a_big_catalog(self):
    assert ModelFetcher._cache_matches_source("chestnut", chestnut_catalog())


class TestJetlinkCatalog(OpenpilotTestCase):
  def test_index_parses_as_a_big_catalog(self):
    catalog = jetlink_catalog()
    bundles = ModelParser.parse_models(catalog)
    assert bundles and len(bundles) == len(catalog["bundles"])
    assert all(len(b.models) == 0 for b in bundles), "nothing to download: a Jetlink host builds its own"
    assert any(b.ref == DEFAULT_BIG_MODEL_REF for b in bundles)
    assert {o.key for b in bundles for o in b.overrides} == {"folder"}

  def test_fetcher_takes_jetlinks_list_without_a_chestnut(self):
    params = store()
    fetcher = ModelFetcherZP(params)
    with mock.patch.object(fetcher_zp.jetlink_adapter, "lists_big_models", return_value=True), \
         mock.patch.object(fetcher_zp.jetlink_adapter, "big_catalog", return_value=jetlink_catalog()) as big, \
         mock.patch("requests.get", side_effect=AssertionError("no sunnypilot fetch")):
      bundles = fetcher.get_bundles_for_source("chestnut")
    big.assert_called_once_with(REQUIRED_JSON_VERSION)
    assert bundles and params.values["ModelManager_ModelsCache_Chestnut"][JETLINK_KEY] is True

  def test_offline_keeps_the_cache(self):
    params = store({"ModelManager_ModelsCache_Chestnut": chestnut_catalog()})
    fetcher = ModelFetcherZP(params)
    with mock.patch.object(fetcher_zp.jetlink_adapter, "lists_big_models", return_value=True), \
         mock.patch.object(fetcher_zp.jetlink_adapter, "big_catalog", return_value=None):
      assert fetcher._fetch_and_cache_models("chestnut") is None
    assert JETLINK_KEY not in params.values["ModelManager_ModelsCache_Chestnut"]


class TestBigCatalogCache(OpenpilotTestCase):
  def cache(self, catalog):
    params = store({"ModelManager_ModelsCache_Chestnut": catalog, "ModelManager_LastSyncTime_Chestnut": int(time.monotonic() * 1e9)})
    return BigCatalogCache(params, "_Chestnut")

  def test_a_mode_flip_expires_it_once(self):
    cache = self.cache(chestnut_catalog())
    with mock.patch.object(fetcher_zp.jetlink_adapter, "lists_big_models", return_value=False):
      assert not cache.get()[1], "sunnypilot's list with a chestnut is current"
    with mock.patch.object(fetcher_zp.jetlink_adapter, "lists_big_models", return_value=True):
      assert cache.get()[1], "the chestnut is gone: refetch jetlink's"
      assert not cache.get()[1], "once: offline the cache stands"

  def test_jetlinks_list_flips_back(self):
    cache = self.cache({**jetlink_catalog(), JETLINK_KEY: True})
    with mock.patch.object(fetcher_zp.jetlink_adapter, "lists_big_models", return_value=True):
      assert not cache.get()[1]
    with mock.patch.object(fetcher_zp.jetlink_adapter, "lists_big_models", return_value=False):
      assert cache.get()[1]


def _bundle(ref, files):
  raw = {"short_name": ref, "display_name": ref, "ref": ref, "is_big": True, "index": 1, "environment": "release", "runner": "tinygrad",
         "generation": 12, "minimum_selector_version": str(REQUIRED_JSON_VERSION),
         "models": [{"type": "supercombo", "artifact": {"file_name": f, "download_uri": {"url": f"https://x/{f}", "sha256": "s"}}} for f in files]}
  return ModelParser.parse_models({"bundles": [raw]})[0]


class TestRetention(OpenpilotTestCase):
  def test_clear_cache_keeps_only_the_pick(self):
    with tempfile.TemporaryDirectory() as root:
      for name in ("picked.pkl", "old.pkl", "old.pkl.cache", "partial.pkl"):
        Path(root, name).write_bytes(b"x")
      os.mkdir(os.path.join(root, "subdir"))
      manager = manager_module.ModelManagerSP.__new__(manager_module.ModelManagerSP)
      manager.params = store({ACTIVE_BUNDLE_KEYS["chestnut"]: _bundle("p", ["picked.pkl"]).to_dict()})
      with mock.patch.object(manager_module.Paths, "model_root", return_value=root):
        manager.clear_model_cache()
      assert sorted(os.listdir(root)) == ["picked.pkl", "subdir"]

  def test_clear_cache_with_no_pick_clears_all(self):
    with tempfile.TemporaryDirectory() as root:
      Path(root, "a.pkl").write_bytes(b"x")
      manager = manager_module.ModelManagerSP.__new__(manager_module.ModelManagerSP)
      manager.params = store()
      with mock.patch.object(manager_module.Paths, "model_root", return_value=root):
        manager.clear_model_cache()
      assert os.listdir(root) == []

  def test_model_root(self):
    from openpilot.common.hardware.hw import Paths
    assert Paths.model_root().endswith(os.path.join("media", "0", "models"))


class TestCarryOver(OpenpilotTestCase):
  def setUp(self):
    super().setUp()
    default_bootstrap._carry_over_queued.clear()

  def test_a_cleared_pick_is_queued_again(self):
    params = store()
    new = _bundle("newref", ["a.pkl"])
    new.internalName = "LS2"
    with mock.patch.object(default_bootstrap.jetlink_adapter, "listed_ref", return_value=None):
      default_bootstrap.carry_over_picks(params, {"chestnut": [new]}, {"chestnut": {"ref": "oldref", "internalName": "LS2"}})
    assert params.values["ModelManager_DownloadRef"] == "newref"
    assert params.values[default_bootstrap.CARRY_OVER_KEY]["chestnut"]["ref"] == "oldref"

  def test_a_recompile_follows_jetlinks_listed_ref(self):
    params = store()
    new = _bundle("newref", [])
    with mock.patch.object(default_bootstrap.jetlink_adapter, "listed_ref", return_value="newref"):
      default_bootstrap.carry_over_picks(params, {"chestnut": [new]}, {"chestnut": {"ref": "oldref", "internalName": "x"}})
    assert params.values["ModelManager_DownloadRef"] == "newref"

  def test_a_pick_gone_for_good_is_dropped(self):
    params = store()
    with mock.patch.object(default_bootstrap.jetlink_adapter, "listed_ref", return_value=None):
      default_bootstrap.carry_over_picks(params, {"chestnut": [_bundle("other", [])]}, {"chestnut": {"ref": "gone", "internalName": "gone"}})
    assert "ModelManager_DownloadRef" not in params.values
    assert default_bootstrap.CARRY_OVER_KEY not in params.values

  def test_offline_waits(self):
    params = store()
    default_bootstrap.carry_over_picks(params, {"chestnut": []}, {"chestnut": {"ref": "r", "internalName": "n"}})
    assert params.values[default_bootstrap.CARRY_OVER_KEY] == {"chestnut": {"ref": "r", "internalName": "n"}}

class TestArtifactSafety(OpenpilotTestCase):
  def test_parse_artifact_rejects_traversal(self):
    for bad in ("../x", "/abs/x", "", ".", "..", "sub/x"):
      with self.assertRaises(ValueError):
        ModelParser._parse_artifact({"file_name": bad, "download_uri": {"url": "https://x/a", "sha256": "0"}})

  def test_process_artifact_rejects_traversal(self):
    import asyncio
    from openpilot.cereal import custom
    mgr = manager_module.ModelManagerSP.__new__(manager_module.ModelManagerSP)
    with tempfile.TemporaryDirectory() as root, mock.patch.object(mgr, "_download_interrupted", return_value=False):
      for bad in ("../x", "/abs/x", "", ".", ".."):
        art = custom.ModelManagerSP.Artifact()
        art.fileName = bad
        art.downloadUri.uri = "https://x/a"
        art.downloadUri.sha256 = "0"
        with self.assertRaises(ValueError):
          asyncio.run(mgr._process_artifact(art, root))

  def test_part_file_removed_on_fail_and_cancel(self):
    import asyncio
    from openpilot.cereal import custom
    mgr = manager_module.ModelManagerSP.__new__(manager_module.ModelManagerSP)
    mgr.selected_bundle = None
    mgr._download_start_times = {}
    with (tempfile.TemporaryDirectory() as root,
          mock.patch.object(mgr, "_download_interrupted", return_value=False),
          mock.patch.object(mgr, "_sync_artifact_progress"),
          mock.patch.object(mgr, "_report_status")):
      art = custom.ModelManagerSP.Artifact()
      art.fileName = "model.pkl"
      art.downloadUri.uri = "https://x/model.pkl"
      art.downloadUri.sha256 = "0" * 64

      async def write_bad(url, path, a):
        Path(path).write_bytes(b"corrupt")  # noqa: ASYNC240

      with mock.patch.object(mgr, "_download_file", side_effect=write_bad), self.assertRaises(ValueError):
        asyncio.run(mgr._process_artifact(art, root))
      assert os.listdir(root) == []

      async def cancel_mid(url, path, a):
        Path(path).write_bytes(b"partial")  # noqa: ASYNC240
        raise manager_module.DownloadCancelled("cancelled")

      with mock.patch.object(mgr, "_download_file", side_effect=cancel_mid), self.assertRaises(manager_module.DownloadCancelled):
        asyncio.run(mgr._process_artifact(art, root))
      assert os.listdir(root) == []

  def test_active_bundle_hidden_while_downloading_ref_matches(self):
    from openpilot.sunnypilot.models.helpers import get_active_bundle
    bundle = _bundle("ref-in-flight", ["a.pkl"])
    with tempfile.TemporaryDirectory() as root:
      Path(root, "a.pkl").write_bytes(b"present")
      params = store({ACTIVE_BUNDLE_KEYS["chestnut"]: bundle.to_dict(), "ModelManager_DownloadRef": "ref-in-flight"})
      with mock.patch("openpilot.sunnypilot.models.helpers.Paths.model_root", return_value=root):
        assert get_active_bundle(params, chestnut=True) is None
        params.values["ModelManager_DownloadRef"] = "other-ref"
        assert get_active_bundle(params, chestnut=True).ref == "ref-in-flight"
