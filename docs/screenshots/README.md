# Screenshots

Images used in the root [README](../../README.md).

The GIF and the `onroad-tesla`, `trip-card` and `home-stats` stills were rendered at 3x scale from public route
`3e2de7ed673817c2/00000076--63bd4c94a4` (Oct 29, 2026), replayed through the device UI code. The lead car marker is hidden in the render.

| File | Shot |
|---|---|
| `teslapilot-demo.gif` | Onroad Tesla theme with compass, trip summary card, Home, swipe back |
| `onroad-tesla.jpg` | Custom onroad UI, Tesla blue, small compass |
| `trip-card.png` | Trip summary card |
| `home-stats.png` | Home with Day and Week stats |
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
