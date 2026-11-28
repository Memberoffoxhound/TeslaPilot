# iPilot iPhone app: first-build plan

Prepared 2026-11-27 for Bruce. Read-only research. Nothing was pushed, posted, or changed on the comma.
Working name: iPilot.

Fork snapshots read (shallow clones, 2026-11-27):
- `Highland-Dev` fde9483 (2026-11-25, version 0.11.24, AGNOS 20.6)  <- best match for your comma 4 on AGNOS 20.6
- `Highland` 1b7ba89 (2026-11-04, version 0.11.23, launch_env.sh says AGNOS 20.2, README says 19.7)
- `release` c1e7525 (launch_env.sh AGNOS 20.3)
- upstream commaai/openpilot master e7d349f

All paths below are inside the fork under `openpilot/...` (the fork nests openpilot code in an `openpilot/` folder).

## 0. Which branch is on the car?

AGNOS 20.6 is pinned in `launch_env.sh` on `Highland-Dev`, `MADD`, `dpbridge`, `mike`, `trip`. `Highland` pins 20.2 and `release` pins 20.3. Since your comma 4 shows AGNOS 20.6, the car is probably running `Highland-Dev` (or one of those siblings), not `Highland`. Confirm in one tap with no change: open `http://<comma-ip>:8089/api/stats` in Safari and read `sw.branch` and `sw.commit` (built in `openpilot/system/webgui/stats.py`, `out["sw"]`).

Why it matters (differences that affect this project):
| Item | Highland-Dev | Highland |
|---|---|---|
| webrtcd video source (`system/webrtc/device/video.py`) | only `livestream*EncodeData` (second encoder, offroad only) | adds `onroad_socks` (qcam and main encoder outputs) when onroad |
| webrtcd started by (`system/manager/process_config.py`) | `or_(livestream, notcar)` | same |
| stream_encoderd | offroad only (`livestream_encoder`) | same |
| web GUI :8089 | yes | yes |

Neither branch runs webrtcd while driving by default (see 1.1).

## 1. Transports that exist today

### 1.1 webrtcd (best fit): `openpilot/system/webrtc/webrtcd.py`
What it is: a small HTTP server plus WebRTC (libdatachannel via the `teleoprtc_repo` submodule). One POST gives one video stream plus one data channel carrying cereal messages as JSON.
- Endpoints (class `WebrtcdHandler`): `POST /stream`, `GET /schema?services=a,b`, `POST /notify`. Port 5001 (`openpilot/system/webrtc/helpers.py: WEBRTCD_PORT = 5001`).
- Request body (`StreamRequestBody` in helpers.py): `{sdp, cameras:["road"|"wideRoad"|"driver"], enabled:true, bridge_services_in:[], bridge_services_out:["carState","deviceState",...], raw:false}`. Response: `{sdp, type}`. There is no trickle ICE: the phone must wait for ICE gathering to finish and send a complete offer in one POST.
- Video codec: H.264 only (teleoprtc `stream.py` uses `add_h264_codec` and `H264RtpPacketizer`). HEVC is not supported by this path.
- Telemetry: `CerealOutgoingMessageProxy` (`system/webrtc/device/messaging.py`) polls a SubMaster every 10 ms and sends `{"type":service,"logMonoTime":..,"valid":..,"data":{...}}` JSON on the data channel labelled `data`. Services seen in `cereal/services.py`: carState, controlsState, selfdriveState, deviceState, modelV2, longitudinalPlan, driverMonitoringState, radarState, gpsLocationExternal.
- Runs by default? NO. `process_config.py` line `PythonProcess("webrtcd", ..., or_(livestream, notcar))` where `livestream` = param `IsLiveStreaming`. That param is cleared at manager start and at ignition on (`openpilot/common/params_keys.h`). Only `athenad.startStream` sets it, and only when `IsOffroad`. Onroad it never runs ("turn car ignition off to use livestreaming", `helpers.py`).
- Listens where? `127.0.0.1:5001` by default (`main()` argparse `--host` default). `process_config.py` passes no arguments. So the iPhone cannot reach it over Wi-Fi today. The file's own docstring in `bridge.py` says to start it with `--host 0.0.0.0`.
- Cameras: offroad uses `stream_encoderd` output, 1280x720 on mici (`system/loggerd/loggerd.h livestream_width/height`), H.264, 5 Mbps with auto bitrate (`system/webrtc/device/bitrate.py`, param `LivestreamEncoderBitrate`). Onroad, the only H.264 encoder output that already exists is `qNarrowRoadEncodeData`: 526x330 at 256 kbps (`loggerd.h qcam_encoder_info`). The main road/wide/cabin encoders are HEVC, which webrtcd cannot packetize as H.264 (Highland's `onroad_socks` maps wideRoad to HEVC, which would not decode; only its qcam road mapping is usable).
- Why not run the second encoder onroad: the fork's own comment in `process_config.py` (`livestream_encoder`): "Starting stream_encoderd while engaged starves controlsd". Do not do that.
- Gotchas found in the code:
  1. Session timeout: `SESSION_TIMEOUT_SECONDS = 300`; normal sessions end after 5 minutes (`run_normal_session`). The app must auto-reconnect, or the fork changes this.
  2. One viewer at a time: a new `/stream` request disconnects the previous session (`handle_get_stream`), including Connect.
  3. SAFETY: `/stream` has no auth, and `bridge_services_in` (client controlled) lets a client publish cereal messages. Before exposing this on a LAN, the fork must force `bridge_services_in=[]` and whitelist `bridge_services_out` to read-only telemetry. Highest-priority hardening item.
  4. Heavy services (modelV2 at 20 Hz as JSON) cost comma CPU. Start with carState, controlsState, selfdriveState, deviceState.

### 1.2 Web GUI: `openpilot/system/webgui/webgui.py` (already on your fork)
- Binds `0.0.0.0:8089`, plain HTTP, no auth, always running (`process_config.py: RestartingPythonProcess("webgui", ... always_run)`).
- `GET /api/stats` returns JSON: software version/branch/commit, onroad/engaged state, CPU temp, CPU %, memory, network type, panda connected/ignition, and `car.v_ego`, `car.set_speed`, `car.cruise_on` (from `webgui/stats.py`, which reads deviceState, pandaStates, carState). Also `/api/shots` (screenshots), `/api/rec` (screen recordings), `/media/...` files.
- This works today with zero changes on the comma. Poll it once per second. Perfect for Milestone 2.
- Not video, and about 1 Hz freshness, so it is a stepping stone, not the HUD.

### 1.3 cereal / msgq over the network
- In this tree `msgq` is shared-memory only on the device. I searched upstream `commaai/msgq` master and found no ZMQ code (only a benchmark example mentioning it). So there is no "ZMQ bridge with ports" to connect to.
- Network access to cereal goes through webrtcd's data channel. `openpilot/system/webrtc/bridge.py` is the official example (a Mac or PC runs it against `<ip>:5001` to mirror services locally). Useful for debugging from the MacBook before writing Swift.
- Caveat: the msgq submodule is not checked out in my clone; I based this on upstream master.

### 1.4 athena / comma connect (remote, through comma's servers)
`openpilot/system/athena/athenad.py` registers JSON-RPC methods the device serves to comma's backend after the user signs in:
- `getMessage(service, timeout)` (line ~362): returns one message of any service as JSON. Good for remote read-only diagnostics.
- `getVersion`, `getNetworkType`, `getNetworkMetered`, `getSimInfo`, `listDataDirectory`, `uploadFilesToUrls`, `listUploadQueue` (logs and files).
- `startStream(sdp, enabled)` (line ~804): remote WebRTC livestream of `wideRoad` plus `carState`/`deviceState` on the data channel. Offroad only. It flips `IsLiveStreaming`, waits for webrtcd, then POSTs to localhost:5001. This is what Connect's Live view uses, parked, via STUN (`stun.l.google.com`, no TURN), so it can fail on strict NAT.
- `startLocalProxy` (line ~725): SSH relay; `wss://ssh.comma.ai/<dongle>` only, local port 22 only (`LOCAL_PORT_WHITELIST = {22}`). Needs SSH keys from GitHub (params `GithubUsername`, `SshEnabled`).
- Auth: you call these through comma's servers with a comma account token. How an iPhone app signs in and the exact athena URL need to be verified against comma's current Connect before building (I did not test it; do it in Milestone 5).

### 1.5 Local Wi-Fi, hotspot, USB
- Comma's own hotspot ("tethering"): IP `192.168.43.1`, default password `swagswagcomma` (`openpilot/system/ui/lib/wifi_manager.py` lines 38-39). The comma then has no internet unless it has its own SIM, so Connect and athena are off.
- iPhone Personal Hotspot: the comma joins it (probably what you do now). The comma keeps internet. iPhone can usually reach its clients; verify in M2.
- Home or garage Wi-Fi: comma and phone on the same router. Easiest for development.
- USB-C: the comma 4 USB-C port is used by Jetlink in this fork (`HIGHLAND.md` Jetlink section; iPhone or Mac runs the big model over USB). Keep Jetlink off for a viewer app, and do not build on USB for the MVP.
- Finding the IP: comma Settings > network, or the hotspot fixed address. (Hostname discovery over mDNS was not verified.)

## 2. iOS feasibility

- WebRTC: Google stopped shipping iOS binaries in 2020 (M80). Use the community SwiftPM package `https://github.com/stasel/WebRTC` (M158, released 2026-11-18, iOS 15+, builds are BSD-3 scripts around unmodified Google WebRTC). It has H.264 and VP8/VP9/AV1 but no HEVC encode/decode on Apple. Matches webrtcd's H.264. LiveKit's SDK talks to a LiveKit server and is the wrong shape here.
- Custom alternative (Path B, later): a tiny Python server added to the fork reads encoder output and sends HEVC over WebSocket; the app decodes with VideoToolbox (`VTDecompressionSession`) or `AVSampleBufferDisplayLayer`. Gives full-res HEVC (main road camera), but you write NAL parsing code. Harder for a beginner; keep for after M4.
- Decoding with WebRTC: the package decodes H.264 with VideoToolbox internally; you display with `RTCMTLVideoView` wrapped in SwiftUI (`UIViewRepresentable`).
- Local Network permission (iOS 14+): add `NSLocalNetworkUsageDescription` to Info.plist; iOS shows a prompt on first LAN access. If denied, requests to `192.168.x.x` fail silently ("no route to host"); re-enable at Settings > your app > Local Network. Plain `http://` to an IP needs App Transport Security: set `NSAppTransportSecurity > NSAllowsLocalNetworking = YES`.
- Background: iOS suspends apps within seconds of leaving the foreground, so streams stop. Plan for foreground use with `UIApplication.shared.isIdleTimerDisabled = true`. Picture in Picture is possible but fiddly; skip.
- CarPlay: not an option. CarPlay apps need an Apple-granted entitlement by category (audio, communication, driving task, EV charging, fueling, navigation, parking, etc.). Apple's driving task guidelines say custom UI such as real-time video is not possible and data may not refresh faster than once per 10 seconds. A live camera app does not qualify. Mount the iPhone in a holder instead.
- Signing and installing:
  - Free Apple ID (Personal Team): runs on your own iPhone, max 3 apps, 10 App IDs, profile expires after 7 days, then rebuild from Xcode (needs the Mac). No TestFlight, no push. Some reports in 2026 of free teams being "banned" (error 0xe8008024); a fresh free Apple ID or paid account avoids it.
  - Paid Apple Developer Program, $99/year: TestFlight builds (up to 90 days each, needs an upload from Xcode on a Mac), a year of signing, App Store.
  - Recommendation: start free, expect the 7-day re-sign, buy the $99 only when the weekly rebuild annoys you.

## 3. Recommended MVP: one path

**iPhone and comma on the same network (home Wi-Fi first, phone hotspot in the car), app talks to webrtcd for H.264 road video plus JSON telemetry for a basic HUD, with the 8089 web GUI as the zero-change warm-up.**

Why this one: it reuses comma's own, tested streaming code (the same one Connect uses), needs only a small read-only fork change, gives video and telemetry over a single connection, and the same app code can later point at a remote signaling route (athena `startStream`) for parked remote viewing.

First version scope: foreground only, one iPhone, qcam-quality road video onroad (526x330) and 720p when parked, HUD with speed, set speed, engaged state, device temperature.

Later path (remote read-only diagnostics, no MacBook): app signs in to comma and calls athena `getMessage`, `getVersion`, `getNetworkType`, and (parked) `startStream`. No fork change needed beyond what M3 adds, but requires the comma to have internet (iPhone hotspot or SIM) and the comma account sign-in to be solved (verify in M5). Not for engaged driving.

Section 7 revises the onroad video path away from webrtcd. Keep M0 to M2 as written here.

## 4. Milestones

Difficulty: 1 = easy, 5 = very hard. Time is for a beginner, evenings.

### M0: Tools (difficulty 1, 1 evening)
- A Mac (MacBook, ideally Apple silicon) with the current Xcode that supports your iPhone's iOS version (iPhone 17 Pro Max ships iOS 26 or newer, so Xcode 26+; check the Mac App Store for macOS requirements).
- Apple ID signed in to Xcode (Settings > Accounts). Cable, and Developer Mode on the iPhone (Settings > Privacy & Security).
- Python 3 on the Mac to run comma's `bridge.py` and curl for testing. Browser and Terminal.
- Learn: what Xcode, a project, a simulator and a signing team are.
- Comma change: none.

### M1: Hello world SwiftUI app on your phone (difficulty 1, 1 to 2 evenings)
- New Xcode project (iOS App, SwiftUI). Put "Hello iPilot" and a button on screen. Run on your iPhone, trust the developer profile.
- Learn: SwiftUI views, `@State`, build and run, 7-day signing.
- Comma change: none.

### M2: Show one live value from the comma (difficulty 2, 2 to 4 evenings)
- Same network. Add Info.plist keys (Local Network usage text, `NSAllowsLocalNetworking`). Use `URLSession` to fetch `http://<comma-ip>:8089/api/stats` every second, decode with `Codable`, show `car.v_ego` (speed in m/s, convert) or `device.cpu_temp`.
- Also confirm `sw.branch` here to settle the branch question.
- Test both home Wi-Fi and the iPhone hotspot (the real in-car case).
- Learn: async/await, JSON decoding, Local Network permission, timers, error states.
- Comma change: none (read-only; the page is already served).

### M3: Video, and live telemetry over webrtcd (difficulty 4, 2 to 4 weeks of evenings)
M3a, fork change (needs Bruce's approval; keep it on the `ifold` branch off `Highland-Dev`; install via Settings > software > custom branch, not by editing files in `/data/openpilot`):
1. New param (e.g. `iPilotStream`, add in `openpilot/common/params_keys.h`) with a settings toggle, default OFF.
2. `process_config.py`: run `webrtcd` also when that param is on (onroad too), and bind to the LAN (change `main()` default host or read an env var). Camera already runs onroad.
3. `video.py`: pick the onroad socket for `road` when onroad (use `qNarrowRoadEncodeData` only; do not map HEVC streams).
4. Harden `handle_get_stream`: force `bridge_services_in=[]`, whitelist `bridge_services_out`, optionally require a shared token header; optional: raise or disable the 5-minute timeout.
5. Test on the bench (parked, offroad) first, then watch controlsd/CPU and `deviceState` on a short drive. Because this alters processes that run while driving, it needs your explicit sign-off and careful testing. Because it does not touch panda safety, driver monitoring, or controls code, the risk is CPU/network load.
M3b, app (SwiftUI):
1. Add the `stasel/WebRTC` package. Create a peer connection, a recv-only H.264 video transceiver, and a data channel labelled `data`.
2. Wait for ICE gathering to complete, POST `{sdp, cameras:["road"], enabled:true, bridge_services_in:[], bridge_services_out:["carState","controlsState","deviceState"]}` to `http://<ip>:5001/stream`, set the remote answer.
3. Show video with `RTCMTLVideoView`; parse JSON data channel messages into a `Telemetry` object.
4. Auto-reconnect every few seconds and on the 5-minute timeout.
- Learn: WebRTC signaling (offer/answer), SwiftUI/UIKit bridging, concurrency, error recovery. Debug first against `bridge.py` on the Mac.
- Quality upgrade options later: 720p when parked (already supported offroad), or Path B (HEVC over WebSocket) for the main camera.

Section 7 revises M3: prefer an in-fork HEVC-plus-telemetry service over onroad webrtcd. The webrtcd steps above stay useful as a parked debug option.

### M4: Onroad overlay and widgets (difficulty 3, 2 to 3 weeks)
- Large readable HUD over video: speed, set speed, engaged state, lane/steering indicators from selfdriveState/controlsState, camera/DM status from driverMonitoringState. Keep text big and glanceable; no tapping while driving, mount the phone.
- Add modelV2 lane lines only after measuring comma CPU (20 Hz JSON is heavy; may need a smaller custom service later). Calibrate overlay positions with `liveCalibration` or fixed offsets.
- Learn: SwiftUI `Canvas`, animations, `ObservableObject`, device orientation, keep-awake, light/dark.
- Comma change: none beyond M3 unless you add services (whitelist them).

### M5: Diagnostics (difficulty 3 to 4, 2 to 3 weeks)
- Local: screen for deviceState (temps, storage, network), pandaStates connection, alerts, version/branch, errors. Use 8089 and webrtcd data.
- Remote (no MacBook): verify comma sign-in and athena endpoint; call `getMessage`, `getVersion`, `getNetworkType`; parked `startStream`. Read-only only. Possible optional pieces: Connect logs and routes pages.
- Learn: OAuth/token storage in Keychain, REST/JSON-RPC, SwiftData for history.
- Comma change: none expected (athena already present). SSH relay stays a desktop tool.

## 5. Approval list for changes on the comma
All inside your fork, nothing edited by hand on `/data/openpilot`:
- M0 to M2: none.
- M3a: params_keys.h, process_config.py, webrtcd.py, video.py, a settings toggle. Branch off `Highland-Dev` on `ifold`, review diff, install via custom software on the comma or keep as a branch you pull into `Highland-Dev` only if you want it permanent. Rollback = switch back to `Highland-Dev` in Settings.

## 6. Open questions for Bruce
1. Do you have a MacBook with Apple silicon, and which macOS? Can it run current Xcode?
2. Free Apple ID for now, or will you buy the $99 developer account (TestFlight, no weekly re-sign)?
3. Which branch is actually on the car? (Check `sw.branch` at `:8089/api/stats`.) Highland-Dev (AGNOS 20.6) is my best guess; Highland pins 20.2.
4. In the car, which network: iPhone Personal Hotspot (comma keeps internet) or the comma's own hotspot?
5. Okay to ship the M3a read-only streaming change as a toggle default OFF, bench tested before any drive?
6. Is low-res road video (526x330) acceptable for MVP while driving, with 720p only while parked?
7. Will it be a personal app only? (That keeps App Store/TestFlight rules out of the picture. The working name is iPilot.)

## 7. Design ideas for the in-fork streamer

Public research on 2026-11-27 included third-party comma streaming designs, the MIT overlay-packs-sdk, and the MIT repo Memberoffoxhound/cviewdetector. Nothing from those sources was pushed, posted, installed, or copied into TeslaPilot.

### License and reuse rule

CommaView (RhynoTech) is a separate product. Its code, installer, binaries, hook scripts, and packet formats are unlicensed for our use and are not copied here. iPilot and its TeslaPilot streaming service will be written from scratch, with our own ports, messages, and names. Do not install that product's runtime as the basis for this app.

### Ideas we are adopting (clean reimplementation only)

The useful design goals, restated in our own words:

- Reuse the HEVC the comma is already encoding while you drive (the main road, wide, and driver cameras), instead of starting a second encoder or using webrtcd onroad. A second encoder can starve controlsd (see the fork comment in `process_config.py`). Video can start when the car does, and the phone can wait for a keyframe. Parked recordings can later pull the comma's own segment files and redraw an overlay on the phone.
- Serve video plus JSON telemetry from a first-class process inside TeslaPilot, turned off by default. Prefer this over a `/data` sidecar or a `continue.sh` boot hook that patches UI files (those conflict with fork updates and can be wiped by AGNOS updates).
- Require pairing before any LAN stream (a pair code or per-phone key, forced empty inbound cereal, an allow-list of outbound telemetry). SSH-via-GitHub is unnecessary if this lives in the fork.
- Later, add discovery (our own name and port, not a third-party packet format) so the app survives DHCP or hotspot IP changes. Typing the IP stays the M2 fallback.
- Decode HEVC on the iPhone with VideoToolbox. The iPhone 17 Pro Max can do this natively, at full road resolution, without WebRTC.
- Start cereal reads with official SubMaster conflate subscriptions of a short list (carState, controlsState, selfdriveState, deviceState). A zero-slot peek is an advanced follow-up only if we prove load or slot issues.
- Queue any update or toggle that restarts processes until the car is offroad.
- Draw a simple Swift HUD from telemetry for MVP. A TeslaPilot-owned UI exporter (path, lanes, alerts) can be an optional later step if the exact in-car look is wanted.
- A phone-as-relay page for the Tesla browser is a later idea, separate from MVP. CarPlay is still not possible.

| Idea | In Highland-Dev today | Adopt? | What it would need on the comma (Bruce must approve) |
|---|---|---|---|
| Peek existing onroad HEVC (`*EncodeData`) instead of webrtcd / a second encoder | encoderd already publishes HEVC onroad; webrtcd is parked-only, localhost:5001, H.264 only; `livestream_encoder` is offroad because it can starve controlsd | Yes, this should become the M3 video path | A first-class, in-fork, read-only process (not a boot patch) that subscribes with conflate, or otherwise peeks, the existing encodes and serves them on the LAN. Toggle default OFF. Bench, then a short drive watching CPU and controlsd. Rollback = switch branch. |
| Decode HEVC on the iPhone with VideoToolbox | n/a (our earlier plan used stasel WebRTC, which has no HEVC) | Yes | None on the comma, once the stream is HEVC. The iPhone 17 Pro Max can decode this natively, at full road resolution, without WebRTC. |
| Auth before any LAN stream | webrtcd `/stream` has no auth and lets the client pick `bridge_services_in` (unsafe) | Yes, required | A pair code or per-phone key shown on the comma or in Settings, forced empty inbound services, allow-list of outbound telemetry. SSH-via-GitHub is unnecessary if this lives in the fork. |
| UDP (or mDNS) discovery so the app survives DHCP / hotspot IP changes | none; :8089 is already LAN-visible if you know the IP | Yes, later (after M2) | A small beacon from the same process, our own name and port, not a third-party packet format. Manual IP stays as fallback (M2 already types the IP). |
| In-tree process, not a `/data` sidecar plus continue.sh patch | TeslaPilot already runs `webgui` as `always_run` in `process_config.py` | Yes, prefer this | Put the streamer in TeslaPilot (`process_config.py` + settings). It then rides his software updates. Avoid `/data/continue.sh` and avoid rewriting UI files at boot (fragile, conflicts with fork updates). |
| Export the fork's exact on-road drawing from the UI process | TeslaPilot already has a custom Tesla HUD, compass, and trip stats | Later, not MVP | A first-class exporter written in TeslaPilot's UI (his files, his socket), sending path / lanes / alerts to the phone. Harder. MVP should draw a simple Swift HUD from telemetry (original M4). |
| Read cereal without disturbing openpilot | official SubMaster with conflate is available | Adopt the *goal*, not a custom peek at first | Start with conflate subscriptions of a short list (carState, controlsState, selfdriveState, deviceState). A zero-slot peek is an advanced follow-up if we ever prove load or slot issues. |
| Parked-only maintenance, never mid-drive | N/A until we ship updates | Yes, if we ever push device updates | Queue any update or toggle that restarts processes until offroad. |
| Browser view for the Tesla screen | :8089 already serves stats and screenshots, no live camera | Later | Phone-as-relay, or a page on the comma. Separate from MVP. CarPlay is still not possible. |
| Install a third-party unlicensed sidecar runtime on this car | not present in the fork | No | Closed, unlicensed sidecar. Do not install it as the basis for iPilot. |

Memberoffoxhound/cviewdetector (MIT) only detects a third-party sidecar and related connections. Its README points at TeslaPilot glue under `selfdrive/ui/mici/onroad/`. Those files are not in the Highland-Dev snapshot we cloned (fde9483, 2026-11-25). Worth a later check, not required for iPilot.

### What this changes in the earlier MVP

Keep M0 to M2 as written (tools, hello-world app, one live value from `:8089/api/stats`, zero comma change).

Revise M3: do not start with webrtcd onroad. The better first video path is a small, open, in-fork TeslaPilot service that reuses encoderd's onroad HEVC (and maybe qcam as a fallback), plus JSON telemetry, with pairing, on the `ifold` branch off Highland-Dev, toggle default OFF. The iPhone decodes HEVC with VideoToolbox. webrtcd remains a parked debug option and a later remote path via athena, not the daily driver. That also answers open question 6: full-res HEVC while driving is in reach, so 526x330 qcam need not be the cap.

M4 stays a Swift overlay from telemetry. A TeslaPilot-owned UI exporter is an optional M4b if Bruce wants the exact in-car look.

M5 is unchanged.

New question for Bruce: are you happy to drop webrtcd as the onroad MVP, and instead approve an in-fork, read-only HEVC-plus-telemetry service with pairing, written from scratch in TeslaPilot?
