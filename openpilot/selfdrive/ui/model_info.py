# Ported from sunnypilot via zoompilot (421d151cf), see LICENSE.sunnypilot.
# Big-model slot only: the small model is the bundled one.
import contextlib
import os
import time

from openpilot.common.hardware.hw import Paths
from openpilot.selfdrive import jetlink_adapter
from openpilot.selfdrive.ui.ui_state import ui_state, ChestnutState
from openpilot.sunnypilot.models.fetcher import get_cached_bundles
from openpilot.sunnypilot.models.helpers import get_active_source, get_selected_bundle, resolve_bundle_by_ref

SMALL_MODEL = "built-in"


def model_cache_size_mb() -> float:
  model_root = Paths.model_root()
  total = 0
  if os.path.isdir(model_root):
    for name in os.listdir(model_root):
      with contextlib.suppress(OSError):
        total += os.path.getsize(os.path.join(model_root, name))
  return total / (1024 ** 2)


def active_source() -> str:
  return get_active_source(chestnut=ui_state.chestnut_present,
                           chestnut_active=ui_state.chestnut_active, chestnut_loading=ui_state.chestnut_loading,
                           offroad=ui_state.is_offroad())


def big_bundles():
  # the manager's list while it runs (offroad), else the cached catalog
  if ui_state.sm.alive["modelManagerSP"] and len(bundles := ui_state.sm["modelManagerSP"].availableBundles):
    return bundles
  return get_cached_bundles(ui_state.params, "chestnut")


def default_model_name() -> str:
  # an empty slot: the Default bundle for a chestnut, jetlink's default without one
  return f"{jetlink_adapter.default_big_model(ui_state.chestnut_present, ui_state.jetlink)} (default)"


def big_model_state() -> str | None:
  return {ChestnutState.UNCOMPILED: 'failed',
          ChestnutState.FAILED: 'failed',
          ChestnutState.LOADING: 'loading',
          ChestnutState.WAITING: 'ready'}.get(ui_state.chestnut_state)


def carrying_model() -> str | None:
  # the big model that drives now, by display name, else None (the small model drives)
  if not ui_state.chestnut_present and ui_state.chestnut_state == ChestnutState.ACTIVE:
    jetlink = ui_state.jetlink
    return jetlink.active_model if jetlink is not None else None
  if active_source() == "chestnut":
    bundle = get_selected_bundle(ui_state.params, "chestnut")
    return bundle.displayName if bundle else default_model_name()
  return None


def big_model_name() -> str:
  bundle = get_selected_bundle(ui_state.params, "chestnut")
  return bundle.displayName if bundle else default_model_name()


def queued_name(current_ref) -> str | None:
  ref = ui_state.params.get("ModelManager_DownloadRef")
  if ref and ref != current_ref:
    if resolved := resolve_bundle_by_ref(ref, {"chestnut": big_bundles()}):
      return resolved[0].internalName
  return None


# the manager's ModelCache key; it restamps it on a successful fetch
MODEL_SYNC_KEYS = ("ModelManager_LastSyncTime_Chestnut",)
MODEL_SYNC_TIMEOUT = 20.0


def refresh_model_list() -> None:
  # zeroing the sync key makes the manager refetch the catalog on its next tick
  for key in MODEL_SYNC_KEYS:
    ui_state.params.put(key, 0)


def refresh_in_progress(started_at: float | None) -> bool:
  # a failed fetch never restamps the key, so the spinner ends at MODEL_SYNC_TIMEOUT
  if started_at is None or time.monotonic() - started_at > MODEL_SYNC_TIMEOUT:
    return False
  return not all(ui_state.params.get(key) for key in MODEL_SYNC_KEYS)
