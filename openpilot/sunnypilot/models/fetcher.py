# Ported from sunnypilot via zoompilot (421d151cf), see LICENSE.sunnypilot.
# Chestnut catalog only.
import os
import time
import requests
from requests.exceptions import (SSLError, RequestException, HTTPError)
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.models.helpers import is_bundle_version_compatible
from openpilot.sunnypilot.models.model_name import DEFAULT_BIG_MODEL_REF, DEFAULT_BIG_MODEL_SHA256
from openpilot.cereal import custom


class ModelParser:
  @staticmethod
  def _parse_download_uri(download_uri_data) -> custom.ModelManagerSP.DownloadUri:
    download_uri = custom.ModelManagerSP.DownloadUri()
    download_uri.uri = download_uri_data.get("url")
    download_uri.sha256 = download_uri_data.get("sha256")
    return download_uri

  @staticmethod
  def _parse_artifact(artifact_data) -> custom.ModelManagerSP.Artifact:
    name = artifact_data.get("file_name")
    if not isinstance(name, str) or name in ("", ".", "..") or name != os.path.basename(name):
      raise ValueError(f"Invalid artifact file_name: {name!r}")
    artifact = custom.ModelManagerSP.Artifact()
    artifact.fileName = name
    artifact.downloadUri = ModelParser._parse_download_uri(artifact_data.get("download_uri", {}))
    return artifact

  @staticmethod
  def _parse_model(model_data) -> custom.ModelManagerSP.Model:
    model = custom.ModelManagerSP.Model()
    model.type = model_data.get("type")
    model.artifact = ModelParser._parse_artifact(model_data.get("artifact", {}))
    return model

  @staticmethod
  def _parse_overrides(overrides_data: dict[str, str]) -> list[custom.ModelManagerSP.Override]:
    overrides = []
    for key, value in overrides_data.items():
      override = custom.ModelManagerSP.Override()
      override.key = key
      override.value = value
      overrides.append(override)
    return overrides

  @staticmethod
  def _parse_bundle(bundle) -> custom.ModelManagerSP.ModelBundle:
    model_bundle = custom.ModelManagerSP.ModelBundle()
    model_bundle.index = int(bundle["index"])
    model_bundle.internalName = bundle["short_name"]
    model_bundle.displayName = bundle["display_name"]
    model_bundle.models = [ModelParser._parse_model(model) for model in bundle.get("models", [])]
    model_bundle.status = 0
    model_bundle.generation = int(bundle["generation"])
    model_bundle.environment = bundle["environment"]
    model_bundle.runner = bundle.get("runner", custom.ModelManagerSP.Runner.snpe)
    model_bundle.is20hz = bundle.get("is_20hz", False)
    model_bundle.minimumSelectorVersion = int(bundle["minimum_selector_version"])
    model_bundle.overrides = ModelParser._parse_overrides(bundle.get("overrides", {}))
    model_bundle.ref = bundle.get("ref")
    if model_bundle.ref == DEFAULT_BIG_MODEL_REF:
      if any(m.artifact.downloadUri.sha256 != DEFAULT_BIG_MODEL_SHA256 for m in model_bundle.models):
        raise ValueError(f"sha256 mismatch for default big model ref {DEFAULT_BIG_MODEL_REF}")
    return model_bundle

  @staticmethod
  def parse_models(json_data: dict) -> list[custom.ModelManagerSP.ModelBundle]:
    found_bundles = [ModelParser._parse_bundle(bundle) for bundle in json_data.get("bundles", [])]
    return [bundle for bundle in found_bundles if is_bundle_version_compatible(bundle.to_dict())]


class ModelCache:
  def __init__(self, params: Params, cache_timeout: int = int(3600 * 1e9), suffix: str = ""):
    self.params = params
    self.cache_timeout = cache_timeout
    self._LAST_SYNC_KEY = f"ModelManager_LastSyncTime{suffix}"
    self._CACHE_KEY = f"ModelManager_ModelsCache{suffix}"

  def _is_expired(self) -> bool:
    current_time = int(time.monotonic() * 1e9)
    last_sync = self.params.get(self._LAST_SYNC_KEY) or 0
    return bool(last_sync == 0) or (current_time - last_sync) >= self.cache_timeout

  def get(self) -> tuple[dict, bool]:
    # (cached data, expired); an empty dict when there is none
    try:
      cached_data = self.params.get(self._CACHE_KEY)
      if not cached_data:
        cloudlog.warning("No cached model data available")
        return {}, True
      return cached_data, self._is_expired()
    except Exception as e:
      cloudlog.exception(f"Error retrieving cached model data: {str(e)}")
      return {}, True

  def set(self, data: dict) -> None:
    self.params.put(self._CACHE_KEY, data, block=True)
    self.params.put(self._LAST_SYNC_KEY, int(time.monotonic() * 1e9), block=True)


class ModelFetcher:
  MODEL_URL_CHESTNUT = "https://raw.githubusercontent.com/sunnypilot/sunnypilot-models/refs/heads/gh-pages/docs/driving_models_chestnut_v28.json"

  MODEL_SOURCES = {
    "chestnut": (MODEL_URL_CHESTNUT, "_Chestnut"),
  }

  def __init__(self, params: Params):
    self.params = params
    self.model_parser = ModelParser()
    self.model_caches = {source: ModelCache(params, suffix=suffix) for source, (_, suffix) in self.MODEL_SOURCES.items()}
    self._refetched: set[str] = set()

  @staticmethod
  def active_source(chestnut_present: bool) -> str:
    return "chestnut"

  def _fetch_and_cache_models(self, source: str) -> list[custom.ModelManagerSP.ModelBundle] | None:
    # None on transport errors; raises on 404 and other fatal HTTP errors
    model_url, _ = self.MODEL_SOURCES[source]
    try:
      response = requests.get(model_url, timeout=10)
      if response.status_code == 404:
        cloudlog.error(f"Models URL returned 404 Not Found: {model_url}")
        raise HTTPError(f"404 Not Found: {model_url}", response=response)
      response.raise_for_status()

      json_data = response.json()
      parsed = self.model_parser.parse_models(json_data)
      if parsed:
        self.model_caches[source].set(json_data)
        cloudlog.debug(f"Successfully updated models cache for {source}")
      return parsed

    except ConnectionError as e:
      cloudlog.warning(f"DNS/connection error while fetching models: {e}")
    except SSLError as e:
      cloudlog.warning(f"SSL error while fetching models: {e}")
    except RequestException as e:
      cloudlog.warning(f"Request transport error while fetching models: {e}")
    except Exception as e:
      cloudlog.exception(f"Unexpected error fetching models: {e}")

    return None

  @staticmethod
  def _cache_matches_source(source: str, cached_data: dict) -> bool:
    bundles = cached_data.get("bundles", [])
    if source == "chestnut":
      return any(bundle.get("is_big") is True for bundle in bundles)
    return not any(bundle.get("is_big") is True for bundle in bundles)

  def get_bundles_for_source(self, source: str) -> list[custom.ModelManagerSP.ModelBundle]:
    if source not in self.MODEL_SOURCES:
      cloudlog.warning(f"Unknown model source: {source}")
      return []

    cached_data, is_expired = self.model_caches[source].get()

    if cached_data and not is_expired:
      # refetched over a mismatch at most once per process: a fresh mismatch means the URL is right
      if self._cache_matches_source(source, cached_data) or source in self._refetched:
        try:
          parsed = self.model_parser.parse_models(cached_data)
        except Exception:
          cloudlog.warning(f"Failed to parse cached models for {source}; refetching", exc_info=True)
        else:
          if parsed:
            cloudlog.debug(f"Using valid cached models data for source {source}")
            return parsed
          # no valid bundles (an old catalog version): refetch
          cloudlog.warning(f"Cached models for {source} have no valid bundles; refetching")
      else:
        self._refetched.add(source)
        cloudlog.warning(f"Cached models for {source} not valid; refetching once")

    fetched_bundles = self._fetch_and_cache_models(source)
    if fetched_bundles is not None:
      return fetched_bundles

    if not cached_data:
      cloudlog.warning("Failed to fetch fresh data and no cache available")

    cloudlog.warning("Failed to fetch fresh data. Using expired cache as fallback")
    try:
      return self.model_parser.parse_models(cached_data)
    except Exception:
      return []


def get_cached_bundles(params: Params, source: str) -> list[custom.ModelManagerSP.ModelBundle]:
  if source not in ModelFetcher.MODEL_SOURCES:
    cloudlog.warning(f"Unknown model source: {source}")
    return []
  _, suffix = ModelFetcher.MODEL_SOURCES[source]
  cached_data = params.get(f"ModelManager_ModelsCache{suffix}")
  if not cached_data:
    return []
  try:
    return ModelParser.parse_models(cached_data)
  except Exception as e:
    cloudlog.warning(f"Failed to parse cached models for source {source}: {e}")
    return []
