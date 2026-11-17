# Big-model catalog and pick for Jetlink, cut down from sunnypilot's model manager (via zoompilot).
# Bundles are plain dicts; small-model bundles are not ported (retired model interface, #38916).
from __future__ import annotations

import re
from collections import namedtuple

# sunnypilot's helpers.REQUIRED_JSON_VERSION on zoompilot develop: the catalog
# entries this build lists, and the selector passed to big_catalog()
REQUIRED_JSON_VERSION = 20

CACHE_TIMEOUT = 3600.0  # seconds, sunnypilot's ModelCache default

# params, all in params_keys.h (none BACKUP: Highland has no such flag)
ACTIVE_BIG = "ModelManager_ActiveBundleChestnut"   # Jetlink's pick; jetlink reads it as keys.big_model
CACHE_BIG = "ModelManager_ModelsCache_Chestnut"    # Jetlink's catalog JSON; jetlink's keys.catalog
SYNC_BIG = "ModelManager_LastSyncTime_Chestnut"    # monotonic ns of the last fetch, 0 asks for one
DOWNLOAD_REF = "ModelManager_DownloadRef"          # a pick the UI queued; jetlink's keys.select
STATUS = "ModelManager_Status"                     # what the manager is doing, for the UI
# a chestnut keeps its own pick, so swapping hardware never drops the other's
CHESTNUT_PICK = "ChestnutModelPick"
CHESTNUT_CACHE = "ChestnutModelsCache"
CHESTNUT_SYNC = "ChestnutModelsSync"
CHESTNUT_REF = "ChestnutModelRef"

KEY_TYPES = {ACTIVE_BIG: "json", CACHE_BIG: "json", SYNC_BIG: "int", DOWNLOAD_REF: "str", STATUS: "json",
             CHESTNUT_PICK: "json", CHESTNUT_CACHE: "json", CHESTNUT_SYNC: "int", CHESTNUT_REF: "str"}

Slot = namedtuple('Slot', 'pick cache sync ref')
SLOTS = {'jetlink': Slot(ACTIVE_BIG, CACHE_BIG, SYNC_BIG, DOWNLOAD_REF),
         'chestnut': Slot(CHESTNUT_PICK, CHESTNUT_CACHE, CHESTNUT_SYNC, CHESTNUT_REF)}


def slot_for(mode: str) -> Slot:
  return SLOTS['chestnut' if mode == 'chestnut' else 'jetlink']


_REF = re.compile(r"[0-9a-f]{40}")
_TRAILING_DATE = re.compile(r"\s*\([A-Za-z]+ \d{1,2}, \d{4}\)\s*$")


def is_bundle_version_compatible(bundle: dict) -> bool:
  """helpers.is_bundle_version_compatible, on the catalog's JSON form."""
  try:
    return int(bundle.get("minimum_selector_version", bundle.get("minimumSelectorVersion", 0))) == REQUIRED_JSON_VERSION
  except (TypeError, ValueError):
    return False


def catalog_bundles(catalog) -> list[dict]:
  """The catalog's usable bundles, newest first. Never raises."""
  try:
    bundles = (catalog or {}).get("bundles", []) if isinstance(catalog, dict) else []
    found = [b for b in bundles if isinstance(b, dict) and _REF.fullmatch(str(b.get("ref")))
             and is_bundle_version_compatible(b) and b.get("display_name")]
    found.sort(key=lambda b: int(b.get("index", 0)), reverse=True)
    return found
  except Exception:
    return []


def folder_of(bundle: dict) -> str:
  overrides = bundle.get("overrides") or {}
  if isinstance(overrides, list):  # the capnp to_dict() form
    overrides = {o.get("key"): o.get("value") for o in overrides if isinstance(o, dict)}
  return str(overrides.get("folder") or "other")


def short_name(name: str) -> str:
  """A display name without the catalog's trailing build date."""
  return _TRAILING_DATE.sub("", name or "")


def to_slot(bundle: dict) -> dict:
  # sunnypilot's ModelBundle.to_dict() form, no files: jetlink fetches the ONNX by ref
  overrides = bundle.get("overrides") or {}
  if isinstance(overrides, dict):
    overrides = [{"key": str(k), "value": str(v)} for k, v in overrides.items()]
  return {
    "index": int(bundle.get("index", 0)),
    "internalName": str(bundle.get("short_name") or ""),
    "displayName": str(bundle.get("display_name") or bundle["ref"][:10]),
    "models": [],
    "status": "downloaded",
    "generation": int(bundle.get("generation") or 0),
    "environment": str(bundle.get("environment") or ""),
    "runner": str(bundle.get("runner") or "tinygrad"),
    "is20hz": bool(bundle.get("is_20hz", False)),
    "minimumSelectorVersion": int(bundle.get("minimum_selector_version", REQUIRED_JSON_VERSION)),
    "overrides": overrides,
    "ref": bundle["ref"],
  }


def find_bundle(catalog, ref: str) -> dict | None:
  return next((b for b in catalog_bundles(catalog) if b.get("ref") == ref), None)
