# Porting to another fork

The nav AR view, the top torque bar, the live trip page, and tripstats ship as one bundle. Copy the modules below, then make the small hook edits (search the tree for `nav-ui hook`). This bundle does not depend on MADS. TeslaPilot keeps an optional lateral-only color on the trip bar when MADS is present; that path is off unless the fork exposes it.

## New modules to copy

Nav UI:

- `selfdrive/navigation/ar_route.py` and `selfdrive/navigation/tests/test_ar_route.py`
- `selfdrive/ui/mici/onroad/nav_ar.py` (road ribbon and air chevrons)
- `selfdrive/ui/mici/onroad/nav_hud.py` (turn card, distance, street, ETA)
- `selfdrive/ui/mici/onroad/nav_torque.py` (`FlatTorqueBar`, a subclass of the stock mici `TorqueBar`)
- `selfdrive/ui/mici/layouts/trip_progress.py` (the live trip page)
- `selfdrive/ui/NAV_UI_PORTING.md` (this file)

Tripstats is required and ships with the trip page. Copy the whole `selfdrive/ui/tripstats/` package:

- `__init__.py` (live tick, view, enabled)
- `recorder.py`, `store.py`, `card.py`
- `progress.py` (trip bar log, numbers, fade, peek)
- `tz.py`, `tzgrid.bin`, `weekstart.json`
- `build_tzgrid.py`, `build_weekstart.py` (rebuild helpers, not needed at runtime)
- `tests/`, `README.md`

Then apply the tripstats hook edits listed in `selfdrive/ui/tripstats/README.md` (params, `tripstats.tick` each UI frame, the summary card, the settings toggle).

## Hook edits (search for `nav-ui hook`)

- `selfdrive/ui/mici/onroad/augmented_road_view.py`: choose AR vs map from `NavView`, run `NavAROverlay` and `NavARHud`, move the DM icon to the upper right in the AR view, shift the vanishing point, hide the side panels, and tell the HUD to put MAX on the right.
- `selfdrive/ui/mici/onroad/hud_renderer.py`: `set_speed_on_right`, render `FlatTorqueBar` instead of the stock arc in the AR view, move MAX left of the DM icon, and skip the wheel and compass in that view. Keep the stock `TorqueBar` for the map and no-nav views. Do not add a `set_flat` flag to comma's `torque_bar.py`.
- `selfdrive/ui/mici/onroad/model_renderer.py`: expose `car_space_transform`, `path_points`, `path_offset_z`, and `theme_rgb` so the overlay can share the model path's projection and color.
- `selfdrive/ui/mici/layouts/main.py`: put `TripProgressPage` in the scroller between home and the camera; call `record()` every frame; run the once-per-drive peek bounce.
- `system/ui/widgets/scroller.py`: `set_peek_px` (a visual offset after snap, so the bounce does not fight paging).
- `selfdrive/ui/ui_state.py`: subscribe to `navRoute`; read the `NavView` param.
- `common/params_keys.h`: `{"NavView", {PERSISTENT, INT, "0"}}` (0 AR overlay, 1 map).
- `selfdrive/ui/mici/layouts/settings/developer.py`: a two-option "nav view" toggle. This tree uses `BigMultiParamToggle`. If a fork does not have that widget, add the same param with whatever two-option control it has.
- `system/athena/athenad.py`: optional `place_name` on `setNavDestination`, stored in `NavDestination`.

Leave comma's `torque_bar.py` and the map-panel parts of `navigation.py` alone. The AR HUD lives in `nav_hud.py` and does not add methods to the map panel.

## Params

- `NavView` (persistent int, default 0): 0 AR overlay, 1 map.
- `NavDestination` may include optional `place_name` (from athena). The trip page falls back to "your destination" without it.
- Tripstats params, from its README: `DriveSummary`, `DriveSummaryLast`, `Timezone`.

## What degrades if a piece is missing

- No `ar_route` / `nav_ar`: no road ribbon or air chevrons. The turn card and ETA still draw if `navInstruction` is alive.
- No live calibration: the overlay hides (`nav_ar.reason`).
- No `navRoute` / no mapsd path: the ribbon may be missing; the turn card still works from `navInstruction`.
- No `place_name`: the trip page says "your destination".
- No `NavView` param or toggle: hardcode AR or map.
- No `set_peek_px` hook: no drive-start bounce. Swipe to the trip page still works.
- No tripstats: the trip page has no live distance, time, engaged %, or bar. This is required; copy the package, do not stub it out.
- No MADS and no `selfdriveStateSP`: the trip bar uses engaged, override, and disengaged only. The lateral-only color is unused. TeslaPilot keeps that color by passing `mads=True` into `classify` when `selfdriveStateSP` is in the SubMaster.
- No theme manager: the AR turn card uses comma green.
- No `always_on_dm`: the trip page dims the DM icon when disengaged, same as stock.

The top torque bar uses the stock `TorqueBar` filters, colors, and visibility (including this fork's existing `steer_status` fade). It is not colored by tripstats engagement. Forks without a `steer_status` fade still inherit whatever `TorqueBar` already does on that fork.

There are no Tesla-specific fonts, wordmarks, or theme assumptions in the new modules.
