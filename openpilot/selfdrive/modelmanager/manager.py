#!/usr/bin/env python3
# modelmanagerd: keeps the active accelerator's catalog fresh and applies the UI's pick. Offroad only.
from __future__ import annotations

import time

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.modelmanager import (CACHE_TIMEOUT, REQUIRED_JSON_VERSION, STATUS, catalog_bundles, find_bundle,
                                              slot_for, to_slot)
from openpilot.selfdrive.modelmanager import store

RETRY_AFTER = (30.0, 60.0, 120.0, 300.0)


def index_catalog() -> dict | None:
  return ja.big_catalog(REQUIRED_JSON_VERSION)


class ModelManager:
  def __init__(self, fetch=index_catalog, clock=time.monotonic, wall=None, log=None, mode=None):
    self.fetch = fetch
    self.clock = clock
    self.wall = wall or (lambda: time.time())  # noqa: TID251  the fetch time the UI shows
    self.log = log or cloudlog
    self.mode = mode or ja.accel_mode
    self.failures = 0
    self._status: dict = {}

  def slot(self):
    return slot_for(self.mode())

  def _expired(self, slot) -> bool:
    last = store.get(slot.sync) or 0
    return last == 0 or int(self.clock() * 1e9) - last >= CACHE_TIMEOUT * 1e9

  def refresh_catalog(self, slot=None, force: bool = False) -> bool:
    """Fetch the catalog if it is due. True when a new one was cached."""
    slot = slot or self.slot()
    if not force and not self._expired(slot):
      return False
    self.report(state="fetching")
    try:
      data = self.fetch()
      if data is None:
        raise ValueError("model index unavailable")
      if not catalog_bundles(data):
        raise ValueError("catalog lists no usable models")
      store.put(slot.cache, data)
      store.put(slot.sync, int(self.clock() * 1e9))
    except Exception as e:
      self.failures += 1
      delay = RETRY_AFTER[min(self.failures, len(RETRY_AFTER)) - 1]
      store.put(slot.sync, int((self.clock() - CACHE_TIMEOUT + delay) * 1e9))
      self.log.warning(f"modelmanagerd: catalog fetch failed ({type(e).__name__}: {e}), retrying in {delay:.0f} s")
      self.report(state="failed", error=f"{type(e).__name__}: {e}"[:200])
      return False
    self.failures = 0
    self.report(state="idle", fetched=int(self.wall()), models=len(catalog_bundles(data)), error=None)
    self.validate_pick(data, slot)
    return True

  def validate_pick(self, catalog, slot=None) -> None:
    slot = slot or self.slot()
    pick = store.get(slot.pick)
    if not isinstance(pick, dict) or not pick.get("ref"):
      return
    if not catalog_bundles(catalog):
      return
    if find_bundle(catalog, pick["ref"]) is not None:
      return
    # same ONNX under a newer ref (jetlink's listed_ref); queue that pick
    listed = ja.listed_ref(str(pick["ref"]))
    if listed and find_bundle(catalog, listed) is not None:
      if store.get(slot.ref) is None:
        store.put(slot.ref, listed)
        self.log.warning(f"modelmanagerd: carrying {pick.get('displayName')} over to {listed[:10]}")
      return
    self.log.warning(f"modelmanagerd: the catalog no longer lists {pick.get('displayName')} ({str(pick['ref'])[:10]}), back to the default")
    store.remove(slot.pick)

  def process_request(self, slot=None) -> None:
    slot = slot or self.slot()
    ref = store.get(slot.ref)
    if not ref:
      return
    catalog = store.get(slot.cache)
    bundle = find_bundle(catalog, str(ref))
    if bundle is None:
      if not catalog_bundles(catalog):
        return  # no catalog yet: the request waits for one
      self.log.warning(f"modelmanagerd: {str(ref)[:10]} is not in the catalog")
      self.report(state="failed", error="that model is not in the catalog")
    else:
      store.put(slot.pick, to_slot(bundle))
      self.log.warning(f"modelmanagerd: big model set to {bundle['display_name']} ({bundle['ref'][:10]})")
      self.report(selected=bundle["ref"], error=None, state="idle")
    if store.get(slot.ref) == ref:
      store.remove(slot.ref)

  def report(self, **fields) -> None:
    status = {**self._status, **fields}
    if status != self._status:
      self._status = status
      try:
        store.put(STATUS, status)
      except Exception:
        pass

  def step(self) -> None:
    slot = self.slot()
    for name, work in (("catalog", self.refresh_catalog), ("request", self.process_request)):
      try:
        work(slot)
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
