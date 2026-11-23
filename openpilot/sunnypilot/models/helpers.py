# Ported from sunnypilot via zoompilot (421d151cf), see LICENSE.sunnypilot.
# Big-model slot only: the bundled small model is not picked here.
import hashlib
import os

from openpilot.cereal import custom
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.common.hardware.hw import Paths
from openpilot.selfdrive.modeld.helpers import chestnut_present

# the json version the sunnypilot-models catalog is built for
REQUIRED_JSON_VERSION = 21

ModelManager = custom.ModelManagerSP

ACTIVE_BUNDLE_KEYS = {
  "chestnut": "ModelManager_ActiveBundleChestnut",
}
_LAST_VALIDATED_RAW: dict[str, dict | None] = {}


def _compute_hash(file_path: str) -> str | None:
  try:
    with open(file_path, 'rb') as file:
      return hashlib.file_digest(file, "sha256").hexdigest().lower()
  except FileNotFoundError:
    return None


async def verify_file(file_path: str, expected_hash: str) -> bool:
  file_hash = _compute_hash(file_path)
  return file_hash == expected_hash.lower() if file_hash else False


def _verify_file(file_path: str, expected_hash: str) -> bool:
  file_hash = _compute_hash(file_path)
  return file_hash == expected_hash.lower() if file_hash else False


def is_bundle_version_compatible(bundle: dict) -> bool:
  # a bundle's minimum_selector_version must match the catalog version this build reads
  return bundle.get("minimumSelectorVersion", 0) == REQUIRED_JSON_VERSION


def _bundle_artifacts(bundle) -> list[tuple[str, str]]:
  artifacts = []
  for model in getattr(bundle, 'models', []) or []:
    artifact = getattr(model, 'artifact', None)
    if artifact and getattr(artifact, 'fileName', None) and getattr(artifact, 'downloadUri', None):
      if sha256 := getattr(artifact.downloadUri, 'sha256', None):
        artifacts.append((artifact.fileName, sha256))
  return artifacts


def _bundle_is_valid_locally(bundle) -> bool:
  model_root = Paths.model_root()
  return all(_verify_file(os.path.join(model_root, file_name), expected_hash)
             for file_name, expected_hash in _bundle_artifacts(bundle))


def _matching_bundle(active_bundle, available_bundles):
  for bundle in available_bundles:
    if active_bundle.ref and bundle.ref:
      if active_bundle.ref == bundle.ref:
        return bundle
    elif active_bundle.internalName == bundle.internalName:
      return bundle
  return None


def _bundle_needs_reset(active_bundle, available_bundles, check_files: bool) -> bool:
  if active_bundle is None:
    return False

  if available_bundles is not None:
    matching_bundle = _matching_bundle(active_bundle, available_bundles)
    if matching_bundle is None:
      return True
    if active_bundle.minimumSelectorVersion != matching_bundle.minimumSelectorVersion:
      return True
    if active_bundle.runner != matching_bundle.runner:
      return True
    if set(_bundle_artifacts(active_bundle)) != set(_bundle_artifacts(matching_bundle)):
      return True

  return check_files and not _bundle_is_valid_locally(active_bundle)


def _parse_active_bundle(raw_bundle):
  try:
    if isinstance(raw_bundle, dict) and raw_bundle and is_bundle_version_compatible(raw_bundle):
      return custom.ModelManagerSP.ModelBundle(**raw_bundle)
  except Exception:
    pass
  return None


def get_selected_bundle(params: Params | None = None, source: str = "chestnut"):
  params = params or Params()
  return _parse_active_bundle(params.get(ACTIVE_BUNDLE_KEYS[source]))


def get_active_source(chestnut: bool | None = None, chestnut_active: bool | None = None,
                      chestnut_loading: bool | None = None, offroad: bool | None = None) -> str:
  if chestnut is None:
    chestnut = chestnut_present()
  state_valid = chestnut_active is not None or chestnut_loading is not None or offroad is not None
  big_active = chestnut and (not state_valid or chestnut_active or chestnut_loading or offroad)
  return "chestnut" if big_active else "qcom"


def get_active_bundle(params: Params | None = None, *, chestnut: bool | None = None):
  # an empty slot is the default: the manager downloads the Default bundle for a chestnut
  params = params or Params()
  if get_active_source(chestnut=chestnut) != "chestnut":
    return None
  bundle = get_selected_bundle(params, "chestnut")
  if bundle is not None and not _big_files_ready(params, bundle):
    return None
  return bundle


def _big_files_ready(params: Params, bundle) -> bool:
  # a pick whose files are missing or being fetched again is not run until the manager has them;
  # existence only, as this is asked every tick and the manager hashes them once per ref
  downloading = params.get("ModelManager_DownloadRef")
  if isinstance(downloading, bytes):
    downloading = downloading.decode()
  if downloading == bundle.ref:
    return False
  model_root = Paths.model_root()
  return all(os.path.isfile(os.path.join(model_root, name)) for name, _ in _bundle_artifacts(bundle))


def big_model_file(params: Params | None = None, chestnut: bool | None = True) -> str | None:
  # the chestnut pick's driving artifact, once all its files are here
  bundle = get_active_bundle(params, chestnut=chestnut)
  if bundle is None:
    return None
  names = sorted((name for name, _ in _bundle_artifacts(bundle)), key=lambda n: not n.endswith('.pkl'))
  return os.path.join(Paths.model_root(), names[0]) if names else None


def resolve_bundle_by_ref(ref: str, source_bundles: dict):
  for source, bundles in source_bundles.items():
    for bundle in bundles:
      if bundle.ref == ref:
        return bundle, source
  return None


def _validate_active_bundle(params: Params, source: str, available_bundles=None) -> dict | None:
  # missing big-model files are fetched again, not a reason to reset the pick
  check_files = source != "chestnut"

  key = ACTIVE_BUNDLE_KEYS[source]
  raw_bundle = params.get(key)
  if not raw_bundle:
    return None

  if _LAST_VALIDATED_RAW.get(key) == raw_bundle:
    return None

  active_bundle = _parse_active_bundle(raw_bundle)
  if source == "chestnut" and active_bundle is not None and available_bundles and _bundle_needs_reset(active_bundle, available_bundles, False) \
     and (listed := _matching_bundle(active_bundle, available_bundles)) is not None:
    # listed anew (jetlink's list for sunnypilot's, or a rebuild): take the new entry in place,
    # since an empty slot would read to jetlink as the Default picked
    cloudlog.warning(f"Active model bundle for {source} is listed anew; updating it in place")
    listed.status = custom.ModelManagerSP.DownloadStatus.downloaded
    params.put(key, listed.to_dict(), block=True)
    _LAST_VALIDATED_RAW[key] = params.get(key)
    return None
  if active_bundle is None or _bundle_needs_reset(active_bundle, available_bundles, check_files):
    cloudlog.warning(f"Active model bundle invalid for {source}; resetting to default")
    params.remove(key)
    _LAST_VALIDATED_RAW[key] = None
    return raw_bundle
  _LAST_VALIDATED_RAW[key] = raw_bundle
  return None


def validate_active_bundles(params: Params, source_bundles: dict) -> dict[str, dict]:
  # clears each slot whose pick no longer matches its catalog; an empty list is a failed fetch
  cleared = {}
  for source, bundles in source_bundles.items():
    if (raw := _validate_active_bundle(params, source, bundles or None)) is not None:
      cleared[source] = raw
  return cleared
