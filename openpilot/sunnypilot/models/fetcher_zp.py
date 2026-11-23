# Ported from zoompilot (421d151cf), see LICENSE.zoompilot.
# The big-model catalog is jetlink's list when no chestnut is fitted, else sunnypilot's as fetched.
# The sunnylink ModelManager_ActiveJson mirror is left out.
from __future__ import annotations

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive import jetlink_adapter
from openpilot.sunnypilot.models.fetcher import ModelCache, ModelFetcher

# stamped on the big-model catalog: it is jetlink's list, not sunnypilot's
JETLINK_KEY = "jetlink"


def _is_jetlinks(catalog) -> bool:
  return isinstance(catalog, dict) and catalog.get(JETLINK_KEY) is True


class BigCatalogCache(ModelCache):
  # expired once when it was fetched for other hardware: a chestnut coming or going changes
  # whose list it is. Offline, the refetch fails and the cache stands until it expires
  def __init__(self, params: Params, suffix: str):
    super().__init__(params, suffix=suffix)
    self._refetched_for: bool | None = None

  def get(self) -> tuple[dict, bool]:
    cached_data, is_expired = super().get()
    jetlink = jetlink_adapter.lists_big_models()
    if cached_data and not is_expired and _is_jetlinks(cached_data) != jetlink and self._refetched_for != jetlink:
      self._refetched_for = jetlink
      cloudlog.warning(f"big-model catalog was fetched for {'a chestnut' if jetlink else 'jetlink'}; refetching")
      is_expired = True
    return cached_data, is_expired


class ModelFetcherZP(ModelFetcher):
  def __init__(self, params: Params):
    super().__init__(params)
    self.model_caches["chestnut"] = BigCatalogCache(params, self.MODEL_SOURCES["chestnut"][1])

  def _fetch_and_cache_models(self, source: str):
    if source != "chestnut" or not jetlink_adapter.lists_big_models():
      return super()._fetch_and_cache_models(source)
    from openpilot.sunnypilot.models.helpers import REQUIRED_JSON_VERSION
    catalog = jetlink_adapter.big_catalog(REQUIRED_JSON_VERSION)
    if catalog is None:  # offline, or no jetlink: the cache stands
      return None
    catalog = {**catalog, JETLINK_KEY: True}
    try:
      parsed = self.model_parser.parse_models(catalog)
    except Exception:
      cloudlog.exception("jetlink's big-model list does not parse")
      return None
    if parsed:
      self.model_caches[source].set(catalog)
    return parsed
