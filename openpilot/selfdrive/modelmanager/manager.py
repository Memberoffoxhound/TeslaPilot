#!/usr/bin/env python3
"""modelmanagerd: keeps the big-model catalog fresh and applies the pick.

zoompilot develop's ModelFetcherZP / ModelManagerSP main loop for the one
slot Highland has, on plain dicts and jetlink v0.9.0's model index:

  - when jetlink_adapter.lists_big_models() (no chestnut fitted), the catalog
    is jetlink_adapter.big_catalog(REQUIRED_JSON_VERSION): jetlink's own index
  - otherwise the chestnut HTTP catalog is fetched for a fitted board
  - a ref the UI queues in ModelManager_DownloadRef is looked up in the
    catalog and stored in ModelManager_ActiveBundleChestnut without files:
    jetlink downloads and verifies the ONNX for that ref itself
  - after a fetch, a pick the catalog no longer lists is carried over via
    listed_ref() (same ONNX under a newer ref) or reset to the default

Offroad only (process_config), so nothing here competes with driving.
No sunnylink, no Git LFS on the device for the pick.
"""
from __future__ import annotations

import json
import time
import urllib.request

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.modelmanager import (ACTIVE_BIG, CACHE_BIG, CACHE_TIMEOUT, CATALOG_URL, DOWNLOAD_REF, JETLINK_KEY,
                                              REQUIRED_JSON_VERSION, STATUS, SYNC_BIG, catalog_bundles, find_bundle,
                                              is_jetlinks, to_slot)
from openpilot.selfdrive.modelmanager import store

FETCH_TIMEOUT = 10.0
RETRY_AFTER = (30.0, 60.0, 120.0, 300.0)


def _log():
  try:
    from openpilot.common.swaglog import cloudlog
    return cloudlog
  except Exception:
    import logging
    return logging.getLogger("modelmanagerd")


def http_fetch(url: str = CATALOG_URL, timeout: float = FETCH_TIMEOUT) -> dict:
  request = urllib.request.Request(url, headers={"User-Agent": "highland-modelmanager"})
  with urllib.request.urlopen(request, timeout=timeout) as response:
    return json.loads(response.read(16 << 20))


class ModelManager:
  def __init__(self, fetch=http_fetch, clock=time.monotonic, wall=None, log=None):
    self.fetch = fetch
    self.clock = clock
    self.wall = wall or (lambda: time.time())  # noqa: TID251  the fetch time the UI shows
    self.log = log or _log()
    self.failures = 0
    self._refetched_for: bool | None = None
    self._status: dict = {}

  def _expired(self, cached) -> bool:
    try:
      last = int(store.get(SYNC_BIG) or 0)
    except (TypeError, ValueError):
      last = 0
    if last == 0 or int(self.clock() * 1e9) - last >= CACHE_TIMEOUT * 1e9:
      return True
    if not catalog_bundles(cached):
      return False  # a failed fetch's back-off is still running
    # fetched for other hardware (a chestnut came or went): once per change
    jetlink = bool(ja.lists_big_models())
    if is_jetlinks(cached) != jetlink and self._refetched_for != jetlink:
      self._refetched_for = jetlink
      self.log.warning(f"modelmanagerd: catalog was fetched for {'a chestnut' if jetlink else 'jetlink'}; refetching")
      return True
    return False

  def _fetch_catalog(self) -> dict | None:
    """Jetlink's index when no chestnut is fitted; else the chestnut HTTP catalog."""
    if ja.lists_big_models():
      catalog = ja.big_catalog(REQUIRED_JSON_VERSION)
      if catalog is None:
        return None
      return {**catalog, JETLINK_KEY: True}
    data = self.fetch()
    if not catalog_bundles(data):
      raise ValueError("catalog lists no usable models")
    return {**data, JETLINK_KEY: False}

  def refresh_catalog(self, force: bool = False) -> bool:
    """Fetch the catalog if it is due. True when a new one was cached."""
    cached = store.get(CACHE_BIG)
    if not force and not self._expired(cached):
      return False
    self.report(state="fetching")
    try:
      data = self._fetch_catalog()
      if data is None:
        raise ValueError("jetlink big-model list unavailable")
      if not catalog_bundles(data):
        raise ValueError("catalog lists no usable models")
      store.put(CACHE_BIG, data)
      store.put(SYNC_BIG, int(self.clock() * 1e9))
    except Exception as e:
      self.failures += 1
      delay = RETRY_AFTER[min(self.failures, len(RETRY_AFTER)) - 1]
      store.put(SYNC_BIG, int((self.clock() - CACHE_TIMEOUT + delay) * 1e9))
      self.log.warning(f"modelmanagerd: catalog fetch failed ({type(e).__name__}: {e}), retrying in {delay:.0f} s")
      self.report(state="failed", error=f"{type(e).__name__}: {e}"[:200])
      return False
    self.failures = 0
    self.report(state="idle", fetched=int(self.wall()), models=len(catalog_bundles(data)), error=None)
    self.validate_pick(data)
    return True

  def validate_pick(self, catalog) -> None:
    pick = store.get(ACTIVE_BIG)
    if not isinstance(pick, dict) or not pick.get("ref"):
      return
    if not catalog_bundles(catalog):
      return
    if find_bundle(catalog, pick["ref"]) is not None:
      return
    # same ONNX under a newer ref (jetlink's listed_ref); queue that pick
    listed = ja.listed_ref(str(pick["ref"]))
    if listed and find_bundle(catalog, listed) is not None:
      if store.get(DOWNLOAD_REF) is None:
        store.put(DOWNLOAD_REF, listed)
        self.log.warning(f"modelmanagerd: carrying {pick.get('displayName')} over to {listed[:10]}")
      return
    self.log.warning(f"modelmanagerd: the catalog no longer lists {pick.get('displayName')} ({str(pick['ref'])[:10]}), back to the default")
    store.remove(ACTIVE_BIG)

  def process_request(self) -> None:
    ref = store.get(DOWNLOAD_REF)
    if not ref:
      return
    catalog = store.get(CACHE_BIG)
    bundle = find_bundle(catalog, str(ref))
    if bundle is None:
      if not catalog_bundles(catalog):
        return  # no catalog yet: the request waits for one
      self.log.warning(f"modelmanagerd: {str(ref)[:10]} is not in the catalog")
      self.report(state="failed", error="that model is not in the catalog")
    else:
      store.put(ACTIVE_BIG, to_slot(bundle))
      self.log.warning(f"modelmanagerd: big model set to {bundle['display_name']} ({bundle['ref'][:10]})")
      self.report(selected=bundle["ref"], error=None, state="idle")
    if store.get(DOWNLOAD_REF) == ref:
      store.remove(DOWNLOAD_REF)

  def report(self, **fields) -> None:
    status = {**self._status, **fields}
    if status != self._status:
      self._status = status
      try:
        store.put(STATUS, status)
      except Exception:
        pass

  def step(self) -> None:
    for name, work in (("catalog", self.refresh_catalog), ("request", self.process_request)):
      try:
        work()
      except Exception:
        self.log.exception(f"modelmanagerd: {name} step failed")


def main() -> None:
  manager = ModelManager()
  manager.report(state="idle")
  while True:
    manager.step()
    time.sleep(1.0)


if __name__ == "__main__":
  main()
