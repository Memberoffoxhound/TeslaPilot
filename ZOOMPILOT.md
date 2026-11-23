# Upstream zoompilot tracking

Upstream reference: `zoompilot/zoompilot` commit `421d151cfa7a5055a6e38b1e29bfa3fae45c01f7` (`421d151cf`).

Ported files are kept as close to upstream `421d151cf` as possible so future `zoompilot` updates merge cleanly.

## License boundary

- `LICENSE.zoompilot` (MIT): zoompilot-original wiring (`default_bootstrap.py`, `fetcher_zp.py`, `accelerator_link.py`, `jetlink_adapter/__init__.py`, `set_speed_assist.py`).
- `LICENSE.sunnypilot` (Custom MIT, permission required for commercial/closed use): sunnypilot-derived model manager, `SPTGPLN1` loader, and models UI (`fetcher.py`, `helpers.py`, `manager.py`, `test_manager_download.py`, `plain_jit.py`, `plain_artifact_compiler.py`, `model_info.py`, `models.py`).

## File mapping and local deltas vs 421d151cf

1. `openpilot/sunnypilot/models/fetcher.py` <- `openpilot/sunnypilot/models/fetcher.py`
   - Chestnut big-model catalog only (drops small-model Firehose/offroad sources).
   - Rejects path-traversal / non-basename `file_name` values in `ModelParser._parse_artifact`.
   - Rejects a Light Speed 2 bundle (`DEFAULT_BIG_MODEL_REF`) whose artifact sha256 does not match `DEFAULT_BIG_MODEL_SHA256`.
   - Updated license header (`LICENSE.sunnypilot`).

2. `openpilot/sunnypilot/models/fetcher_zp.py` <- `openpilot/sunnypilot/models/fetcher_zp.py`
   - Drops sunnylink `ModelManager_ActiveJson` mirror and `qcom` small-model source.
   - Imports `openpilot.selfdrive.jetlink_adapter`.
   - Updated license header (`LICENSE.zoompilot`).

3. `openpilot/sunnypilot/models/helpers.py` <- `openpilot/sunnypilot/models/helpers.py`
   - Chestnut big-model slot only (comma bundled small model stays default when no chestnut/Jetlink is active).
   - Drops sunnylink / small-model helpers.
   - Updated license header (`LICENSE.sunnypilot`).

4. `openpilot/sunnypilot/models/manager.py` <- `openpilot/sunnypilot/models/manager.py`
   - Chestnut slot only; keeps `clear_model_cache()` and `ModelManager_DownloadRef` coordination.
   - Enforces realpath-under-root validation in `_process_artifact`.
   - Downloads atomically to `<target>.part`, verifies sha256 on `.part`, then `os.replace`s to `<target>`, removing `.part` on failure or cancellation.
   - Reads `ChestnutSeen` each tick (`self.chestnut_seen = self.params.get_bool("ChestnutSeen")`) so a Jetlink-Off boot clear in `jetlink_power.py` is visible.
   - Updated license header (`LICENSE.sunnypilot`).

5. `openpilot/sunnypilot/models/default_bootstrap.py` <- `openpilot/sunnypilot/models/default_bootstrap.py`
   - Keeps `carry_over_picks` across selector bumps / catalog rebuilds; omits zoompilot Firehose small-model bootstrap.
   - Updated license header (`LICENSE.zoompilot`).

6. `openpilot/sunnypilot/models/model_name.py` (local constant extract)
   - Holds `DEFAULT_BIG_MODEL`, `DEFAULT_BIG_MODEL_REF`, and `DEFAULT_BIG_MODEL_SHA256` matching `421d151cf` / chestnut_v28 Light Speed 2 (`Light Speed 2`, `b92fc4828664f8767bce5e92f1630ed319cbe509`, `680a8d629785f2b1d1a2b0e40d0dfbcd0f7291c21e20c51259f1d768a22ec217`).

7. `openpilot/sunnypilot/models/tests/test_manager_download.py` <- `openpilot/sunnypilot/models/tests/test_manager_download.py`
   - Chestnut-slot download, retry, cancel, and default big-model tests adapted to this fork without sunnylink/small-model slots.
   - Updated license header (`LICENSE.sunnypilot`).

8. `openpilot/selfdrive/modeld/plain_jit.py` <- `openpilot/sunnypilot/modeld_v2/helpers.py`
   - Extracted standalone `SPTGPLN1` loader (without `modeld_v2` driver-monitoring/camera helpers).
   - Replaces `eval` in `_dtype` with `getattr(dtypes, ...)` + `DType` check.
   - Adds sha256 payload digest verification and `_CacheUnpickler.find_class` restriction on `.cache` reads alongside `_MetadataUnpickler` for `extras`.
   - Adds `ty` ignore comments on tinygrad monkey-patches.
   - Updated license header (`LICENSE.sunnypilot`).

9. `openpilot/selfdrive/modeld/tests/plain_artifact_compiler.py` <- `openpilot/sunnypilot/modeld_v2/plain_artifact_compiler.py`
   - Compile-time test fixture helper only; updated license header (`LICENSE.sunnypilot`).

10. `openpilot/selfdrive/ui/model_info.py` <- `openpilot/selfdrive/ui/sunnypilot/model_info.py`
    - Big-model slot only; lowercases `"(default)"` suffix for mici UI consistency.
    - Updated license header (`LICENSE.sunnypilot`).

11. `openpilot/selfdrive/ui/accelerator_link.py` <- `openpilot/selfdrive/ui/sunnypilot/accelerator_link.py`
    - Uses `openpilot.selfdrive.jetlink_adapter` import path.
    - Updated license header (`LICENSE.zoompilot`).

12. `openpilot/selfdrive/ui/mici/layouts/settings/models.py` <- `openpilot/selfdrive/ui/sunnypilot/mici/layouts/models.py`
    - Adapted to TeslaPilot mici UI widgets, big-model-only slot (no driving options, no sunnylink favorites), and lowercased empty-state `"no models available"`.
    - Updated license header (`LICENSE.sunnypilot`).

13. `openpilot/selfdrive/jetlink_adapter/__init__.py` <- `openpilot/sunnypilot/jetlink_adapter/__init__.py`
    - Placed at `openpilot/selfdrive/jetlink_adapter/` with stock defaults and runtime exported for UI (`modelDataV2SP` absent).
    - Updated license header (`LICENSE.zoompilot`).

14. `openpilot/selfdrive/controls/lib/set_speed_assist.py` (via zoompilot / sunnypilot PR #2083)
    - Gated on `openpilotLongitudinalControl` (`has_longitudinal_control`); updated license header (`LICENSE.zoompilot`).
