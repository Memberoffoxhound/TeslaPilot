# accelerator icon progress: ('download', frac) or ('compile', None), else None
import math

PERCENT_STAGES = ('download', 'upload')  # jetlink stages with a real fraction


def provisioning(mode: str, chestnut_download: float | None, jetlink_progress):
  # chestnut_download: the model manager's download of the chestnut's model, 0..1
  if mode == 'chestnut':
    return None if chestnut_download is None else ('download', max(0.0, min(1.0, chestnut_download)))
  if mode == 'jetlink' and isinstance(jetlink_progress, dict):
    stage = str(jetlink_progress.get('stage', ''))
    if stage in ('', 'ready', 'failed'):
      return None
    return ('download', _frac(jetlink_progress)) if stage in PERCENT_STAGES else ('compile', None)
  return None


def chestnut_download(model_manager) -> float | None:
  # the model manager's download of the chestnut's pick (modelManagerSP), 0..1, else None
  try:
    bundle = model_manager.selectedBundle
    if bundle.status != 'downloading' or not len(bundle.models):
      return None
    return sum(m.artifact.downloadProgress.progress for m in bundle.models) / len(bundle.models) / 100.
  except Exception:
    return None


def _frac(progress: dict) -> float:
  try:
    return max(0.0, min(1.0, float(progress.get('frac') or 0.0)))
  except (TypeError, ValueError):
    return 0.0


def pulse(t: float) -> float:
  return 0.35 + 0.65 * (0.5 - 0.5 * math.cos(t * 6.0))
