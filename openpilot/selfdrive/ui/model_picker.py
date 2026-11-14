# Models page logic, no UI. Picks queue in ModelManager_DownloadRef for modelmanagerd, as sunnypilot does.
from __future__ import annotations

import time

from openpilot.selfdrive import jetlink_adapter as ja
from openpilot.selfdrive.modelmanager import (ACTIVE_BIG, CACHE_BIG, DOWNLOAD_REF, STATUS, SYNC_BIG, catalog_bundles, folder_of,
                                              short_name)
from openpilot.selfdrive.modelmanager import store

DEFAULT_LABEL = "default"
SMALL_MODEL = "built-in"
SMALL_NOTE = ("The small model is the one Highland ships; it updates with Highland.\n" +
              "sunnypilot's small models use the model interface comma replaced\n" +
              "in September 2026, so Highland's modeld cannot run them.")


def bundles() -> list[dict]:
  return catalog_bundles(store.get(CACHE_BIG))


def folders() -> list[tuple[str, list[dict]]]:
  """(folder, bundles newest first), the folder with the newest model first."""
  grouped: dict[str, list[dict]] = {}
  for b in bundles():
    grouped.setdefault(folder_of(b), []).append(b)
  return sorted(grouped.items(), key=lambda kv: max(int(b.get("index", 0)) for b in kv[1]), reverse=True)


def picked() -> dict | None:
  pick = store.get(ACTIVE_BIG)
  return pick if isinstance(pick, dict) and pick.get("ref") else None


def default_name() -> str:
  from openpilot.selfdrive.ui.ui_state import ui_state
  return ja.default_big_model(ui_state.chestnut_present, ui_state.jetlink)


def big_model_label() -> str:
  pick = picked()
  if pick is None:
    return f"{default_name()} ({DEFAULT_LABEL})".lower()
  return short_name(str(pick.get("displayName") or pick["ref"][:10])).lower()


def queued() -> str | None:
  ref = store.get(DOWNLOAD_REF)
  return str(ref) if ref else None


def status() -> dict:
  value = store.get(STATUS)
  return value if isinstance(value, dict) else {}


def list_label() -> str:
  s = status()
  if queued() or s.get("state") == "fetching":
    return "fetching..."
  if s.get("state") == "failed":
    return "failed: " + str(s.get("error") or "offline")[:40].lower()
  n = len(bundles())
  if not n:
    return "not fetched yet"
  fetched = s.get("fetched")
  when = time.strftime("%b %d %H:%M", time.localtime(fetched)).lower() if isinstance(fetched, (int, float)) else ""
  return f"{n} models" + (f", {when}" if when else "")


def model_note(ref: str) -> str:
  """'ready' when the Jetson has built it, 'downloaded' when on the comma, else ''."""
  try:
    return str(ja.model_state(ref) or "")
  except Exception:
    return ""


def select(ref: str) -> None:
  store.put(DOWNLOAD_REF, ref)


def reset_to_default() -> None:
  store.remove(DOWNLOAD_REF)
  store.remove(ACTIVE_BIG)


def refresh() -> None:
  store.put(SYNC_BIG, 0)
