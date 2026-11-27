# Porting to another fork

The nav AR view, the top torque bar, the live trip page, and tripstats ship as one bundle. Copy the modules below, then make the small hook edits (search the tree for `nav-ui hook`). This bundle does not depend on MADS. TeslaPilot turns on an optional lateral-only color on the trip bar when `selfdriveStateSP` is in `sm.data`; that path stays off on forks that do not expose it.

## New modules to copy

Nav UI:

- `selfdrive/navigation/ar_route.py`, `ar_overlay.py`, and `selfdrive/navigation/tests/test_ar_route.py`, `test_nav_ar.py`
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

- `selfdrive/ui/mici/onroad/augmented_road_view.py`: only when navd has a live route (`route_active`: a valid and alive `navInstruction`; a leftover `navRoute` does not count, and the gate stays true for 8 s after the last live instruction so a failed reroute does not snap to stock) choose AR vs map from `NavView`, run `NavAROverlay` and `NavARHud`, move the DM icon to the upper right in the AR view, shift the vanishing point, hide the side panels, and tell the HUD to put MAX on the right. With no live route the onroad view is stock (confidence ball, left DM, steering arc, side panel), even if `NavDestination` is set. A destination alone must not open the map panel. The map panel's "GPS fix / Route / Map frames" status is shown only while that panel is up (live route or the 8 s hold, and map frames not ready), not for dest-without-route. The road view reads `nav_layout` flags. The AR view stays up during an onroad alert so the critical wheel icon can replace the hidden torque bar; the map panel still hides.
- `selfdrive/ui/mici/onroad/hud_renderer.py`: `set_speed_on_right`, render `FlatTorqueBar` instead of the stock arc in the AR view, move MAX left of the DM icon, and skip the normal wheel and compass in that view. Still draw the critical warning icon on the flat bar when a critical alert hides the bar. Keep the stock `TorqueBar` for the map and no-nav views. Do not add a `set_flat` flag to comma's `torque_bar.py`.
- `selfdrive/ui/mici/onroad/model_renderer.py`: expose `car_space_transform`, `path_points`, `path_offset_z`, and `theme_rgb` so the overlay can share the model path's projection and color. Pass `theme_rgb` into `NavARHud.render`.
- `selfdrive/ui/mici/layouts/main.py`: put `TripProgressPage` in the scroller between home and the camera, visible only while a live route is active; call `record()` every frame; run the once-per-drive peek bounce only when that page is available; scroll back to the camera on a warning or critical alert (and no touch is in progress) or when the route ends while the trip page is on screen. Do not insert or remove the trip page mid-scroll or mid-touch.
- `system/ui/widgets/scroller.py`: `set_peek_px`. Peek is applied when placing items, not added to the snap offset, so the bounce does not fight paging.
- `selfdrive/ui/ui_state.py`: subscribe to `navRoute`; read the `NavView` param and `NavDestination` (store the dict as `nav_destination`) on the params worker thread.
- `common/params_keys.h`: `{"NavView", {PERSISTENT, INT, "0"}}` (0 AR overlay, 1 map).
- `selfdrive/ui/mici/layouts/settings/developer.py`: a two-option "nav view" toggle. This tree uses `BigMultiParamToggle`. If a fork does not have that widget, add the same param with whatever two-option control it has.
- `system/athena/athenad.py`: optional `place_name` on `setNavDestination`, stored in `NavDestination`. The new argument needs a validator (`either(one_of(None), regex(r"[^\x00-\x1f]{0,80}"))`); without it TeslaPilot's rpc dispatcher refuses to register the method and athenad will not start. An empty string is accepted and not stored. Nav2Pilot `setNavRoute` does not carry `place_name`, so routes from the phone app always say "your destination".

Leave comma's `torque_bar.py` and the map-panel parts of `navigation.py` alone. The AR HUD lives in `nav_hud.py` and does not add methods to the map panel.

## Params

- `NavView` (persistent int, default 0): 0 AR overlay, 1 map.
- `NavDestination` may include optional `place_name` (from athena). The trip page falls back to "your destination" without it.
- Tripstats params, from its README: `DriveSummary`, `DriveSummaryLast`, `Timezone`.

## What degrades if a piece is missing

- No live route from navd: stock onroad UI. No AR overlay, chevrons, turn card, ETA, map panel, trip page, or peek bounce, even if a destination is set. A stale `navRoute` left after navd stops does not count. The map panel and trip page appear only after navd is publishing a valid `navInstruction` (and they stay up for 8 s after it drops). The "GPS fix / Route / Map frames" status lives on the map panel and is not shown when there is no route.
- No live calibration: the overlay hides (`nav_ar.reason`) and the map panel takes over, after the usual hold.
- No `place_name`: the trip page says "your destination".
- No `NavView` param or toggle: hardcode AR or map.
- No `set_peek_px` hook: no drive-start bounce. Swipe to the trip page still works.
- No tripstats: the trip page has no live distance, time, engaged %, or bar. This is required; copy the package, do not stub it out.
- No MADS and no `selfdriveStateSP` in `sm.data`: the trip bar uses engaged, override, and disengaged only. The lateral-only color is unused. TeslaPilot turns that color on by passing `mads=True` into `classify` when `'selfdriveStateSP' in sm.data`.
- No theme color passed into `NavARHud.render`: the AR turn card uses comma green.
- No `always_on_dm`: the trip page dims the DM icon when disengaged, same as stock.

The top torque bar uses the stock `TorqueBar` filters, colors, and visibility (including this fork's existing `steer_status` fade). It is not colored by tripstats engagement. Forks without a `steer_status` fade still inherit whatever `TorqueBar` already does on that fork.

There are no Tesla-specific fonts, wordmarks, or theme assumptions in the new modules.
