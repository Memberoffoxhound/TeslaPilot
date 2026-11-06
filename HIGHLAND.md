> User-facing README: [README.md](README.md). This file is Highland working notes only.

# TeslaPilot — Highland

These notes describe **Highland-Dev**: version **0.11.23**, synced through comma master `89e7e0a4c` (openpilot **0.11.3**).

AGNOS is **20.3** (`launch_env.sh`). The first boot on an older OS flashes it. Other branches may use different versions.

## opendbc pin

`.gitmodules` points `opendbc_repo` at `Memberoffoxhound/TeslaPilot-opendbc` (same-org sibling, not commaai/opendbc — Tesla 3-bit / coop steering cannot live on comma's SHA).

Structure matches comma: gitlink SHA is what ships, not the branch tip. The SHA is **comma openpilot master's opendbc pin plus Tesla-only commits**:

- comma base: `1df34867` (the pin in comma master `89e7e0a4c`)
- extras: 3-bit `DAS_steeringControlType`, cooperative steering, scroll-wheel cancel, local EPS fingerprint overlay after stock identification

```bash
cd opendbc_repo
git fetch origin
git checkout <gitlink SHA>
cd ..
git add opendbc_repo
git commit -m "opendbc: bump Highland (comma pin + Tesla extras)"
```

Current gitlink: `bfff3f6e` (comma `1df34867` plus Highland changes).

## Fingerprint

Stock recognition runs first. Unknown cars remain onroad in dashcam mode. The UI can save a Model 3/Y EPS reply in `/data/teslapilot/fingerprints/tesla-fw-v1.json`; normal firmware matching uses it after restart. No platform is forced.

## Params

| Param | Default | Meaning |
|---|---|---|
| `AutoLaneChangeEnabled` | off | Nudgeless lane change >25 mph, 0.75 s after the blinker, once Tesla BSM is clear. Warning + slide-to-enable. rav4kumar / sunnypilot. |
| `LaneColor` | tesla | `0` Openpilot green, `1` Tesla Autopilot blue (lanes, wheel, confidence, compass, DM). |
| `CompassSize` | small | Custom UI only. `0` small left, `1` large top-right. |
| `TeslaStepAside` | on | While Tesla Autosteer/FSD is selected (not TACC) or Autopilot/FSD/Summon is active, openpilot goes passive before CarParams: `noOutput`, relay never closes. 5 s alert, then display off (touch wakes). Back via onroad cycle once Tesla is idle on TACC 3 s and in P or cruise off. `TeslaSteppedAside` (cleared on ignition) is the per-drive state. See `selfdrive/car/tesla_step_aside.py`. |
| `ParkOffroad` | off | "Go Offroad in Park" (warning confirm; also sets `DriveSummary`). After R/D this ignition cycle, Park held 3 s, not engaged → normal offroad. Only R/D returns onroad (new route); ignitionCan staying on never does. Ignition off ≥ 5 s clears it. No gear frames 2 s → stock until the next ignition cycle. Summon/Autopark stays offroad. `selfdrive/car/park_offroad.py` (parkd), hardwared `not_parked`. |
| `ParkOffroadState` | 0 | parkd's output: 0 none, 1 parking, 2 parked. Cleared on manager start only, re-asserted every second. |
| `DriveSummary` | off | Trip card as the onroad page when a trip ends (stopped, ≥ 0.1 mi / 30 s); stock scroll to home after 20 s (`SHOW_S`) or a tap; swipe back to see it until the next drive. With `ParkOffroad`: up at the first Park sample with brightness held, and R/D skips `ONROAD_DELAY` and the brightness ramp. Any car; see PORTING.md. |
| `DriveSummaryLast` | — | The one trip-stats store (JSON): 400 days of totals, lifetime, best stretch, best streak, last drive, drives not stored yet. See `selfdrive/ui/tripstats/README.md`. |
| `Timezone` | — | Time zone for trip-stats days, looked up from `LastGPSPosition` in the offline 190 KB map (`tzgrid.bin`). The system zone is used until the first GPS fix. Written off the UI thread. There is no manual override. |

## Trip stats

Trip stats live in one param, `DriveSummaryLast`, written by one recorder in the UI (`selfdrive/ui/tripstats`). Home's Day / Week, the card, Statistics and the web page all read the same numbers from it. There are no qlog scans, no `/data` files and no background jobs.

A drive is saved every 30 s while it runs. If power is cut, it closes at its last save, and its card comes up once at the next start as "last trip summary".

Days follow the device's time zone. GPS gives the position, `tzgrid.bin` turns it into a zone, and the zone goes in `Timezone`. With no GPS fix yet, the system zone is used. Each drive is saved with its end time and the zone offset at that moment, so a later zone change never moves it. A drive that ends on a wrong clock waits until the clock is valid. Weeks start on the local first day of the week for the `Timezone` zone's country (`weekstart.json`, from CLDR), or Sunday with no GPS zone. Details: `selfdrive/ui/tripstats/README.md`.

Older builds left `/data/trip_stats.json`, `/data/trip_seed_cache.json`, `/data/trip_meter.json` and
`/data/trip_*.lock` behind. Nothing reads them now, and they are safe to delete.

## Alpha longitudinal (stock)

For a recognized Tesla, stock master sets `alphaLongitudinalAvailable = True`.

- Visible on development branches (`AlphaLongitudinalEnabled` is `DEVELOPMENT_ONLY`).
- Can change onroad while not engaged. Cannot while engaged.
- Change requests an onroad cycle (`OnroadCycleRequested`) so panda safety reinits.

Tesla stock ACC until this is on. Experimental is gated on openpilot long.

## Screenshots / LAN

Hold display 3s → `/data/media/0/screenshots`. Web GUI `system/webgui` on **8089**, runs at boot (manager `RestartingPythonProcess`, always_run), no auth: stats, screenshots, UI screen recording.

## Jetlink

`jetlink_repo` is pinned at `9cfde98` (**v0.9.0**, adapter API 4). The comma, Jetson and phone runtime versions must agree.

- `selfdrive/jetlink_adapter` uses Jetlink's `Stock` adapter and `Hooks`; keep it aligned with zoompilot's porting guide.
- **Settings → models** offers the big-model picker and off/USB/iOS link setting. There is no charge-phone control; `JetlinkChargePhone` remains default-off because Jetlink's keys require it.
- Without a chestnut, Jetlink supplies its own model catalog and downloads the selected ONNX. With a chestnut, the model manager uses the chestnut HTTP catalog.
- Jetlink's `Status` and `/dev/shm/jetlink/modeld.json` feed the existing chestnut icons. Waiting is dim; active is green.
- selfdrived reports available/lost/active events (`log.capnp` @107–109; Tesla step-aside is @106). A swap briefly blocks entry with `bigModelLoading`; link events do not disengage.
- hardwared reports an unavailable accelerator and coordinates shutdown. The launch hook stops USB-C charging while the link is enabled; ADB is unavailable while Jetlink owns the port.
- modeld retains the stock USB-host exclusion when detecting a chestnut cable and publishes `lat_delay` for the joining model.

## CommaView

Like sunnypilot, this tree carries no CommaView code, toggle or daemon. CommaView's external installer owns its UI patch, runtime and boot hook.

## Git LFS

The branch installs with no LFS fetch. Every file comma keeps in LFS is a normal git blob here (`.gitattributes` exempts it), except `models/big_driving_tinygrad.pkl` (776 MB, over GitHub's 100 MB limit): that stays a pointer, is excluded in `.lfsconfig` (`fetchexclude`), and is pulled from comma's LFS store by the modeld build only when a chestnut is present (`big_model_source.ensure_big_pkl`). `chestnut_compiled()` is false for a pointer, so jetlink / the small model are used instead of a crash.

`python3 scripts/teslapilot_lfs.py` checks this (`--fix` converts newly added LFS files). `selfdrive/test/test_no_lfs_pointers.py` runs it in the test suite.

## Safety

Does not touch driver monitoring, actuation checks, or panda safety. See [SAFETY.md](SAFETY.md).
