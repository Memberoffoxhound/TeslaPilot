# Ported from zoompilot (421d151cf), see LICENSE.zoompilot.
# carry_over_picks keeps the big-model pick across a selector bump or a rebuilt catalog.
# zoompilot's Firehose small-model default is left out: the comma keeps its bundled small model.
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive import jetlink_adapter
from openpilot.sunnypilot.models.helpers import get_selected_bundle

CARRY_OVER_KEY = "ModelManager_CarryOver"
_carry_over_queued: set[str] = set()


def carry_over_picks(params, source_bundles: dict, cleared: dict[str, dict]) -> None:
  # run after validate_active_bundles with the picks it cleared. Once the catalog lists the same
  # model (by ref, else by ONNX for jetlink's list, else by short name) its download is queued.
  # Kept until the slot is filled; queued once per model per process so a failing one never spins
  pending = params.get(CARRY_OVER_KEY) or {}
  changed = False
  for source, raw in cleared.items():
    if isinstance(raw, dict) and raw:
      pending[source] = {"ref": raw.get("ref", ""), "internalName": raw.get("internalName", "")}
      changed = True

  for source, pick in list(pending.items()):
    bundles = source_bundles.get(source) or []
    if get_selected_bundle(params, source) is not None:  # downloaded, or the user picked another
      del pending[source]
      changed = True
      continue
    if not bundles:  # offline, or the catalog is not fetched yet
      continue
    match = next((b for b in bundles if pick["ref"] and b.ref == pick["ref"]), None) or \
      _same_onnx(bundles, pick["ref"]) or \
      max((b for b in bundles if b.ref and b.internalName == pick["internalName"]), key=lambda b: b.index, default=None)
    if match is None:
      cloudlog.warning(f"Model pick {pick} is not in the {source} catalog, leaving the default")
      del pending[source]
      changed = True
    elif match.ref not in _carry_over_queued and params.get("ModelManager_DownloadRef") is None:
      _carry_over_queued.add(match.ref)
      params.put("ModelManager_DownloadRef", match.ref)
      cloudlog.warning(f"Carrying the {source} pick {match.displayName} over to the new catalog (queued ref {match.ref})")

  if changed:
    if pending:
      params.put(CARRY_OVER_KEY, pending)
    else:
      params.remove(CARRY_OVER_KEY)


def _same_onnx(bundles: list, ref: str):
  # the bundle jetlink's list names a pick's ONNX under: a recompile is listed under its newest ref
  listed = jetlink_adapter.listed_ref(ref)
  return next((b for b in bundles if b.ref == listed), None) if listed else None
