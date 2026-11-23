# Screenshots

Images used in the root [README](../../README.md).

The onroad, trip summary, Home, and Statistics stills were rendered at 3x scale from public route
`3e2de7ed673817c2/00000076--63bd4c94a4` (Oct 29, 2026), replayed through the device UI code.
The lead car marker is hidden in the onroad render. The Settings stills are headless renders of
the same UI. The Home, Statistics, Settings, and non-nav onroad stills are from Highland-Dev
0.11.24. The trip summary card and the onroad navigation stills were re-rendered from the rebased
`mike` tip at 3x scale. The card uses lowercase day and week labels and includes the filtered
column, with a count of 3 recovered steering-sensor dropouts. The demo GIF is from an earlier
render of the same route.

| File | Shot |
|---|---|
| `teslapilot-demo.gif` | Onroad Tesla theme with compass, trip summary card, Home, swipe back |
| `onroad-tesla.jpg` | Custom onroad UI, Tesla blue lanes, small compass |
| `onroad-nav.jpg` | Custom onroad UI with Nav2Pilot guidance, Tesla blue route |
| `onroad-nav-mads.jpg` | Same nav layout with MADS steering and the desire path |
| `trip-card.png` | Trip summary card, including the filtered column |
| `home-stats.png` | Home with day and week stats, version 0.11.24 |
| `settings.png` | Settings, with driving where toggles used to be |
| `settings-driving.png` | Settings → driving, lowercase labels |
| `settings-models.png` | Settings → models, lowercase labels |
| `icon-tacc.png` | TACC badge |
| `icon-long.png` | LONG badge |
| `icon-mads.png` | MADS badge |
| `icon-wheel-engaged.png` | Onroad wheel: openpilot engaged |
| `icon-wheel-mads.png` | Onroad wheel: MADS steering alone |
| `icon-wheel-mads-paused.png` | Onroad wheel: MADS paused |
| `icon-wheel-override.png` | Onroad wheel: driver override |
| `icon-wheel-off.png` | Onroad wheel: disengaged |
| `icon-ssa.png` | Set Speed Assist icon (`icons_mici/set_speed_assist.png` on black, so it shows on GitHub's light theme) |
| `stats-ring.jpg` | Statistics: engaged ring |
| `stats-weekly.jpg` | Statistics: weekly engaged |
| `stats-monthly.jpg` | Statistics: monthly engaged |

The badge and wheel icons are rendered from the device UI code (`LongModeBadge`, `MadsBadge` and `HudRenderer`) on black, 342x240.
Badges are at 5x scale and wheels at 3x, with the default theme.
