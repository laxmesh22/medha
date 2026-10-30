# Agent handoff: Auri device + webcam CV → clinic station dashboard

Written 2026-10-29 for the next agent. Showcase: **31 Oct 2026, IIT Bombay**. Read `agenthandoff.md` (rules, maths)
and `AGENTS.md` (working rules, log) first. Items marked **[unverified]** were not tested on hardware.

---

> **For the person continuing the device (29–30 Oct hand-over).** This file is the whole story of the device and
> station work so far: what exists, what was measured, what is broken, what to do next, and how we work (Claude
> plans and reviews, Cursor/Grok executes, §9). Start with §0, then §6 (TODO) and §8 (stages). Nothing from briefs
> 021–033 is committed yet: commit it first (§6 step 1) so your work starts from a clean tree.



## RESUME HERE (31 Oct 03:11, continue in Claude)

The phone holds the three bands over Bluetooth and forwards raw samples to the clinic station over Wi-Fi.
The station turns those into a pose after the worn position is locked. The phone does not compute angles.
USB to the laptop is only for install and logs. It is not required while the bands are worn.

**Do this next, in order**
1. Station, if it is not already up: `hub/.venv/Scripts/python.exe -m physiobuddy_hub run --webcam 0 --straps off --motionnet off --pose-smoothing light --port 8012`. The phone is the only Bluetooth central. Do not also connect the bands from the laptop. Never open the straps' COM ports.
2. Phone and laptop on the same Wi-Fi. The app field is `192.168.4.55` (check `Get-NetIPAddress -InterfaceAlias Wi-Fi`). Forwarding socket is `ws://<laptop>:8012/ws/phone`.
3. Wear the three boxes as they sit (boards lie flat, cases are crooked). Refresh http://127.0.0.1:8012. Press **Guided calibration**. Stand still, arms hanging, until the N-pose is accepted. Then one straight raise **toward the camera**, not out to the side.
4. The figure stays frozen until that N-pose is actually saved. `strap_pose` is null while `calibration.state` is `none`.

**Bands (address map in `external/AURIMEDIC/app/lib/services/ble_bands.dart`)**
- `CC:BA:97:00:FE:FD` upper arm. Radio name is still `AURI-TRUNK` (new ESP32-S3, firmware 0.1.0 protocol 2, D4/D5). Do not "fix" it back to the waist.
- `14:63:93:BD:AB:6E` forearm. `AURI-ARM`, streams cleanly near −40 dBm.
- `14:63:93:BD:B4:7A` waist. Radio name is still `AURI-ARM`. Weak at range (about −78 to −95). This is the original arm board, not a new chip.

**Why the figure was not moving (measured 31 Oct 01:22)**
All three were connected at about 50 Hz and `strap_pose` was still null. An N-pose capture got upper arm 153, forearm 153, trunk 36. The old rule required 50 samples from every sensor, so the waist rejected the whole capture and nothing was saved. `MIN_NPOSES` is now 20, and a short sensor is left out instead of failing the arms. The person must stand still (gyro peak ≤ 0.3 rad/s) and run Guided calibration again. That has not been confirmed since the change.

**Worn position is the zero**
`StrapCalibration.from_npose` makes the quaternion captured while worn the identity pose (arms down, trunk up), including a flat or slanted box. `refine_from_raise_direction` then sets forward from the direction the arm actually moved, not from the gyro axis. The mount is written to `hub/straps_mount.local.json` (git-ignored) and reloaded for the same side. A new N-pose replaces it.

**Three.js**
`web/src/avatar.js` `solveStrap` poses the chest from `Bip01_Spine1`. Do not aim `Bip01_Spine`: on this rig it parents both thighs, which threw the whole body onto its back. The other arm stays down (standing pose), not out in the T-pose. Display frame: thorax X anterior, Y up, Z right → three.js x = −Z, y = Y, z = X (toward the camera). A correct forward raise is +Z.

**Phone app (separate repo)**
`external/AURIMEDIC`, branch `auth0-supabase`, remote `github.com/nvmjustunique/AURIMEDIC`. Not inside this git tree. It keeps the GATT links and forwards quaternion, gyro, gravity, sequence, and valid. It does not show angles. Android cleartext is allowed so `ws://` to the laptop works. The socket retries direct, with no HTTP proxy. If the station shows searching while the phone says bands ready, the Wi-Fi socket is down.

**Do not**
- Do not flash this firmware tree onto the arms. The boards that are worn still run 0.1.0 protocol 2. This commit includes later protocol v3 power/sleep edits that were not flashed. A C3 image must not be written to the S3 (`FE:FD`).
- Commit `env.local.json`, Auth0 keys, or `hub/straps_mount.local.json`.
- Treat the network as a source of angles. Degrees come from `hub/physiobuddy_hub/core/strap_kin.py` only. Missing data stays unavailable, never 0.

**Checks already run**
`pytest hub/tests/test_strap_kin.py hub/tests/test_phone_straps.py` and the N-pose test passed. `cd web && npm run build` produced `index-Dv5zkGUh.js`. A full `pytest hub/tests ml/tests` was not re-run for this push.

## RESUME HERE (older, 29–30 Oct — read after the block above)
1. Read §0 "Remaining stages" and the last 10 lines of `tools/cursor_bridge/LIVE/STATUS.md`.
2. `git status --short` and `git log --oneline -5` in `D:\medha`; `git -C external/AURIMEDIC status` (branch
   `auth0-supabase`). Last pushed commit here: `1d7913d` on `laxmesh22/medha` branch `auri-device`.
3. Ask the user: (a) did they run SQL 038 then 039 in Supabase (not confirmed at hand-off)? (b) did they add `https://auri-patient.vercel.app`
   to the Auth0 SPA app? (c) may you push the AURIMEDIC branch to github.com/nvmjustunique/AURIMEDIC?
4. Start the bridge in a new terminal tab (use xhigh if `agent models` lists it):
   `& 'D:\medha\tools\cursor_bridge\LIVE\cursor_bridge.ps1' -Model grok-4.7-xhigh -Workspace D:\medha`
   and the low-token watcher under Monitor: `hub/.venv/Scripts/python.exe tools/cursor_bridge/watch_done.py LIVE`.
   Next brief number = highest `to_cursor/NNN.md` + 1 (LIVE: 041 was the last at hand-off; LIVE_IMU: 002). Check `from_cursor/041.md` first.
5. Commit the uncommitted work in small commits (033–039 hub/web, migrations + schema + DATA_MODEL.md, docs),
   after `pytest hub/tests ml/tests -q` and `cd web && npm run build`.
6. Station for a demo: `hub/.venv/Scripts/python.exe -m physiobuddy_hub run --webcam 0 --straps
   14:63:93:BD:B4:7A,14:63:93:BD:AB:6E --motionnet off --port 8012` (check `__main__.py --help` for the exact
   strap/exposure flags added in 026/035), open http://127.0.0.1:8012. Never open the straps' COM ports.
7. Then work down "Remaining stages". Update §0 and this section when you stop, so the next agent can resume.

## 0. Read this first: goal, what this session did, what is next

**Goal.** Auri is a frozen-shoulder rehab system. At the showcase (31 Oct) a person stands in front of the clinic
station: the **webcam CV** measures shoulder angles from geometry, a **wireless BNO085 strap** on the upper arm adds
orientation, both feed the hub, and the station page (three.js avatar, angles, rep counting, pain check) shows it live.
The clinician dashboard (`clinician/`, live at auri-clinician.vercel.app) is where physios see patients; linking
station sessions to it is a later stage (S13). "Fully functioning device" = stages S0–S8 in §8.

**What this session (29 Oct, Claude + Cursor/Grok via the bridge) did**
1. Strap firmware from scratch (`firmware/`): XIAO ESP32-C3 + BNO085, own `bno_lite` driver, BLE protocol v2
   (37-byte packets). Verified 50 and 100 Hz, 0 gaps (commits de23b09 → 9510dd4). Release zip for a friend
   (`firmware/release/`, git-ignored). Board 2's original firmware backed up in `firmware/backups/` (never delete).
2. Hub ingest: `run --straps off|auto|ADDR`, calibration endpoints, strap angles, Straps card (ba8d4b6, 16258cb).
3. Flutter patient-app guide for the shared Supabase + Auth0 (`docs/PATIENT_APP_FLUTTER.md`, 9f877d9). Open: the
   user still has to give the app's package name to continue step by step.
4. Teammate's CV engine (github.com/abdulmueez3-14/AURIII, pinned 0011377 in `external/AURIII`, own Python 3.12 venv)
   wired in as the station's webcam mode: `tools/auri_cv_worker/worker.py` → `hub/physiobuddy_hub/capture/auri_cv.py`.
   Bridge briefs 021–023: about 18 fps, 40 ms median latency, empty room gives all angles + shrug unavailable,
   137 tests pass. **These files are NOT committed yet** — review and commit them first (§6 step 1).
5. Board 1 (USB AB:6C, BLE AB:6E): looked dead here because opening COM7 resets it. With COM7 left closed it
   streams over BLE: 50.07 Hz, 0 gaps, 100% valid, |q| = 1.000, gravity 9.245 (brief 024). Not a solder fault.
   Its `i2c_errors` counter sits at 35 (stable); watch it.
6. Second bridge `LIVE_IMU` opened for the wireless strap; plan IMU-001 answered (phases A–E in §6/§8).
7. Clinician dashboard changes from the user's notes (sign-up, emergency, attention page) are in the working tree,
   deployed to Vercel by Cursor, **not committed** — commit them separately from the device work.

**Latest results (29 Oct evening, bridge briefs 024–029)**
- 024: board 1 over BLE only (COM7 closed): 50.07 Hz, 0 gaps, 100% valid.
- 025: hub 8012 with webcam + strap AB:6E: strap ~51 Hz 0 gaps, camera ~20 fps, N-pose OK (99 samples),
  apparent elevation 6° arm down, 138 tests pass. Not committed.
- 026: both straps on battery. Both firmwares say unit 1, so the hub maps by address: board 2 B4:7A -> upper_arm,
  board 1 AB:6E -> forearm. AB:6E 50.08 Hz 0 gaps alone, some gaps once both linked. **B4:7A connects but sends
  0 IMU** (sensor not streaming; power-cycle / wiring check). 139 tests pass.
- 027: Vision panel shows the real camera: downscaled JPEG preview (320 px) on a side channel under the skeleton,
  on by default with `--webcam`, toggle in the panel, **never recorded or saved**. The hint names the missing
  parts (hips / wrist / elbow). 140 tests pass. Found: during strap GATT activity camera inference rose to 321 ms
  (3.2 fps) then recovered to 47 ms -> Bluetooth is blocking the camera path.
- 028: station UI now uses the clinician dashboard tokens (page #F5F2EA, Deep Teal #0A4A4F, Jost wordmark, same
  logo). `--ink-3` measured 3.55:1, so labels use `--ink-2` for >= 4.5:1. 140 tests pass, web build OK.
- 029: StrapLink (bleak) moved to its own thread + event loop; the camera frame path never waits on BLE. 60 s with
  a simulated disconnect: camera 20.0–20.4 fps, strap reconnect 4.3 s and 5.9 s, backoff capped at 10 s. New test:
  a slow strap does not delay frames. Hub shows a "hardware: power-cycle / check BNO wiring" note when a strap
  connects but its sensor stays empty. 141 tests pass.
- 030: still-board accuracy, board 1 (AB:6E), 60 s: yaw drift **2.48°/min** (over the 2°/min target: BNO085
  game rotation vector has no magnetometer, so redo the N-pose at the start of every set), gravity error
  −0.036 m/s² (pass), 0 gaps, |q| = 1. N-pose accepted (101 samples). Raise calibration is rejected while the
  board is still (correct: it needs a real arm raise). `tools/compare_cam_strap.py` written: logs camera and
  strap angles side by side from /ws/live and prints mean/|mean|/RMS/max difference, correlation and lag.
- 031: board 2 recovered after the user power-cycled it: 50 Hz, 0 gaps, 100% valid, |q| 1.000, gravity 9.83–9.86.
  The stale hardware note clears when the sensor reports present. Both straps were then live at 51–52 Hz.
- 032: camera fps 10 -> **~30** (60 s windows 29.9–30.3). Cause: the webcam read took 75 ms. Fix: DirectShow
  backend, manual exposure −5, capture overlapped with inference. Preview/send/ingest are < 1 ms.
- 033: Vision draws image + skeleton from the same frame id, mirror applies to both, Straps card shows
  "off / searching". (Its headless fps numbers were throttling artefacts; see 035.)
- 035: the 032 manual exposure made the image almost black (mean brightness 4/255, no landmarks). Back to auto
  exposure, colour: brightness 145, 20 fps, 10/17 landmarks >= 0.5. In a visible browser the preview draws at
  18.4 fps, 14 ms median delay. **Open: the skeleton/tracking itself still feels laggy to the user** (the video is
  fine) — next CV task: profile MediaPipe model size/complexity, smoothing filter, and pipeline latency.

- 040 (done): skeleton vs picture lag. Stage timings (60 s, webcam only): camera read 49 ms (frame period, ~20 fps),
  inference 25 ms, landmark send 0.7 ms, JPEG encode/send 0.5 ms, hub 0.1 ms, websocket < 1 ms (no backlog).
  Cause: the preview JPEG was shown before that frame's pose existed (picture 1 frame ahead; only 13% of paints had
  the matching skeleton) plus an extra ~70 ms follow in the 3D figure. Fix: the preview is held until its pose
  arrives; display joints use a fast One-Euro (6 Hz, speed gain 0.4) + 30 ms lead (capped 8 cm 3D / 5% of frame
  2D); a missing joint stays missing; new hub flag `--pose-smoothing off|light|normal` (default light; `off` =
  measured pose; measured angles and rep counting are unchanged). Result: skeleton-vs-image offset 1 -> 0 frames,
  match 13% -> 100%, pose age in browser 102 -> 64 ms (p95 220 -> 117), drawn fps 17.9. New
  `hub/physiobuddy_hub/core/pose_smooth.py`. 145 tests pass.
- 041 (running at hand-off): skeleton **blinks** and is inaccurate when the user is very close to the camera (face
  fills the frame, 16.9 fps): visibility hysteresis (show >= 0.6, hide < 0.35 or after N missed frames), hold last
  good landmark <= 150 ms (display only; angles stay unavailable when data is missing), lower MediaPipe confidences
  to ~0.5, check the skeleton/preview coordinate mapping, and a "Step back 1-2 m" hint. Check
  `LIVE/from_cursor/041.md` and `LIVE/STATUS.md`; verify with the user at ~2 m in good light.
- LIVE_IMU 002 (done, compile-only, nothing flashed): PROTOCOL.md version label fixed; **protocol v3** = STATUS
  type `0x07` power record (6 bytes) + COMMAND `0x07` (run / sleep / idle timeout), the 16-byte v2 status is
  unchanged and v2 firmware (both boards today) still works; hub `battery_pct` (3300->0, 4200->100 mV, clamped)
  and `battery_low` (<= 15% = 3435 mV), null when `battery_mv` is null; shown on the Straps card. Firmware
  (compile only): warn at `AURI_BAT_WARN_MV` 3500 (haptic pattern 3 + flag bit0) and stop at `AURI_BAT_STOP_MV`
  3350 (reports off, bit1) are **placeholders until the brown-out voltage is measured**; the strap can buzz before
  the card says low (22% vs 15%). Idle policy: after the idle timeout minutes disconnected -> reports off,
  ~1 s advertising, 500 ms sleep / 500 ms awake (the prebuilt Arduino-ESP32 3.3.12 C3 controller has
  modem/auto light sleep off, so a long `esp_light_sleep_start()` would stop advertising); wake by BLE connect or
  `-DAURI_WAKE_BTN=1` on D2 (only if BNO INT is not on D2). Default timeout 0 = disabled. Builds (C3):
  divider off 608157 B flash / 24476 RAM, divider on 618843 / 24692, wake button 619317 / 24692. 107 hub tests pass.
  **Phase E (signed BLE OTA) not started**; never first try it on board 2.
  Hardware checklist for the user: (1) 3.7 V PCM cell + slide switch in series with BAT+, polarity checked, charge
  only off the body (the C3 charger runs whenever USB-C is plugged); (2) 100 k BAT+ -> D1, 100 k D1 -> GND, 100 nF D1
  -> GND, then build `-DAURI_HAS_BATTERY_DIVIDER=1`; (3) optional D2 button + 10 k pull-up (`-DAURI_WAKE_BTN=1`);
  (4) a meter in series with the cell (not a USB meter). Measure: cell voltage where the running board resets
  (meter vs STATUS `battery_mv`) -> replace 3500/3350; series current streaming / advertising / idle.
- Seen in `LIVE/STATUS.md` from another session (unverified, ask the user): a "waist Pi firmware / SD card flash"
  attempt on 30 Oct ~18:26 failed (no removable disk, USB port reset code 43); a long-running clinic-station
  `--straps auto` shell exited after ~70 min with its log truncated at 1 MB (camera stayed healthy).
- Section 11 (new): the full plan for 3 straps + camera, accuracy protocol and the same in the Flutter app (M1-M10).

**Patient app (AURIMEDIC, github.com/nvmjustunique/AURIMEDIC), briefs 034–039**
- Cloned to `external/AURIMEDIC` (git-ignored), local branch `auth0-supabase`. **Not committed, not pushed** to
  the friend's repo; ask the user before pushing.
- 034: sign-in moved from Supabase Google OAuth to **Auth0** (Google + email); Supabase gets the Auth0 ID token.
  Data moved to the shared schema: `patients` row on first sign-in, `link_patient_with_code`, care plan,
  `sessions` + `session_exercises` (angles null when not measured), booked `video_calls` -> Jitsi.
  applicationId / bundle id `com.auri.auri`. Auth0 **Native** app (its own client id) for Android/iOS; the web
  build uses the dashboard's **SPA** client.
- 036: live checks all pass (dashboard 200, Auth0 discovery, Google 302, Universal Login, Supabase RLS blocks
  anonymous reads). Flutter 3.47.9 installed user-scope; analyze clean, 38 tests. Web build deployed:
  **https://auri-patient.vercel.app**. The user confirmed **Google sign-in works in the app**.
- APK: `external/AURIMEDIC/app/build/app/outputs/flutter-apk/app-debug.apk` (debug, ~178 MB, not signed).
- 038: migration `clinician/supabase/migrations/20261030_patient_app.sql` (reps_rejected nullable,
  `sessions.ended_early`, `patients.intake` jsonb, RPC `preview_clinician_by_code` returning only name/title/
  clinic/city to signed-in users). `schema.sql` updated. **The user must run it in the Supabase SQL editor**
  (Claude/Cursor have no service key and must not use one).
- 039 (done): dedicated patient-data tables: inventory of everything the app collects, `DATA_MODEL.md`,
  `patient_intake` (versioned history, replaces `patients.intake` with data moved), `patient_consents`,
  `patient_settings`, email from the Auth0 token; RLS = patient owns, linked clinician reads; dashboard shows
  intake + consent read-only. Second migration `20261030b_patient_tables.sql`, to run after 038's. `patients.intake` kept one release. Reviewed by Claude: RLS on all three tables (patient own rows, linked clinician read-only), no destructive statements. Inventory and design in `clinician/supabase/DATA_MODEL.md`.

**Remaining stages, in order (next agent)**
1. Confirm the user ran 038 then 039 SQL; then a full phone test: sign in -> link with an `AU-` code (name shows
   first) -> intake -> session -> it appears on the clinician dashboard.
2. Auth0 SPA app: add `https://auri-patient.vercel.app` to callback, logout and web origins (web sign-in).
3. Commit the AURIMEDIC branch and, with the user's OK, push it (or open a PR) to the friend's repo; commit the
   migrations/docs in this repo (tasks 033–039 are uncommitted here too).
4. Skeleton/tracking lag (CV).
5. Strap accuracy test with a person (below), then wireless phases A–C (battery, divider, cutoff).
6. Voice coach voice = the video's narration voice (ask which tool made `video/out/voice.wav`).
7. Station sessions -> Supabase so clinicians see clinic-station results too (S13).
8. Release APK (signed) when the team wants a store/testing build.
9. **Three straps + camera, accuracy and the Flutter app: full plan in section 11** (milestones M1-M10).

**Never yet done (the important next test):** a person wearing both straps (B4:7A upper arm, AB:6E forearm, lid
out, same orientation every time), standing 2–2.5 m back with hips and wrist in view: N-pose 3 s ->
"Calibrate", one forward raise -> "Raise", then 5 slow forward raises and 5 side raises while
`hub/.venv/Scripts/python.exe tools/compare_cam_strap.py --seconds 60` runs. That gives the real
camera-vs-strap agreement. Record the numbers here.

- Flutter patient app: `docs/PATIENT_APP_FLUTTER.md` rewritten as a full step-by-step guide for the friend's app
  (Auth0 Native app, Android/iOS config, Dart code with the Auth0 ID token on Supabase, patient row,
  `link_patient_with_code`, care plan, sessions, video calls, error table). Supabase URL and package name are
  placeholders; iOS steps and the code are not yet run on a phone.

**Open right now**
- **Voice coach voice (user request):** the station's voice coach (`web/src/voiceAgent.js`, browser speech today)
  must use the same voice as the narration in our video. The only narration file is `video/out/voice.wav`
  (28 Oct 18:17, 5.4 MB); nothing in the repo records which TTS engine/voice made it. First ask the user which
  tool/voice that was, then switch the coach to it (pre-rendered clips for fixed lines, or the same engine live),
  keeping a text-only fallback and the 0–10 pain-check lines unchanged.
- Review and commit 021–028 in small commits (W1 webcam, straps mapping, preview, theme), separate from `clinician/`.
- First real test with a person: camera + both straps on the arm, N-pose then forward raise; compare camera and
  strap angles. Then the showcase script in `docs/SHOWCASE.md`.
- LIVE_IMU: send the phase A/B brief (slide switch + D1 divider) when the user has soldered them.

**Videos, CAD, Blender, Remotion, skills:** see `docs/VIDEO_AND_TOOLS_METHOD.md` (how every Auri video was made, step by step).

**How to continue:** use the bridge exactly as in §9 — the next agent thinks and reviews, Cursor (Grok) executes.

## 1. Current state

### Firmware (committed)
| Commit | What |
|---|---|
| de23b09 | strap firmware v0.1 |
| 3cb9886 | own BNO08x SHTP driver `src/bno_lite` (multi-instance) |
| 57364fe | first real BNO085 data |
| 9510dd4 | protocol v2: combined 37-byte IMU+gyro+gravity packets, non-blocking IMU reset, 400 ms boot window |

Verified on **board 2**:
- 3 resets, sensor found every time, 0 I2C errors
- 50 Hz and 100 Hz with **0 sequence gaps**
- IMU reset recovers in 368 ms; |q| = 1; gravity 9.80 m/s²

Board identities:
- **Board 2 (good):** XIAO ESP32-**C3** rev v0.4. MAC 14:63:93:bd:b4:78, BLE 14:63:93:BD:B4:7A. BNO085 at 0x4A on D4/D5. Last seen on COM14; COM numbers change between plug-ins (COM7 on 29 Oct).
- **Board 1:** USB 14:63:93:BD:AB:6C, BLE 14:63:93:BD:AB:6E. Works: 50 Hz, 0 gaps over BLE (brief 024). Opening its COM port on this laptop resets it, so test it over BLE only. `i2c_errors` stable at 35.
- Aditya's original firmware is backed up at `firmware/backups/board2_b478_original_full.bin` (git-ignored). **Never delete it.**
- Release zip: `firmware/release/auri_strap_v0.1.0/` (git-ignored). It holds merged .bin images (flash at 0x0) and SHA256SUMS.

### Hub strap ingest (committed)
- ba8d4b6 (A1): `hub/physiobuddy_hub/straps/` holds `protocol.py`, `link.py` (StrapLink, bleak) and `calibrate.py`. Live test: about 50 Hz, 0 gaps.
- 16258cb (A2): calibration endpoints, `StrapKinematics` angles in the state, the `imu_features` block sent to `MotionNetRunner.push(imu=...)`, and the station Straps card.
  - N-pose was accepted live (87 samples).
  - True elevation shows *unavailable* because there is no trunk strap yet; apparent elevation is stable.
- bdb5c20: AGENTS.md log entry.

### W1: webcam mode (**uncommitted**, written by Cursor, not yet reviewed by Claude)
Files:
- `external/AURIII/`: the teammate's repo, pinned at 0011377, with its own Python 3.12 `.venv`. It is git-ignored.
- `tools/auri_cv_worker/worker.py`
- `hub/physiobuddy_hub/capture/auri_cv.py` (`WebcamSource`, `adapt_line`)
- Edits to `hub/physiobuddy_hub/pipeline.py` and `hub/physiobuddy_hub/__main__.py`
- `web/index.html`, `web/src/main.js`, `web/src/style.css`
- `README.md`, `docs/SHOWCASE.md`
- `hub/tests/fixtures/auri_cv_frame.jsonl`, `hub/tests/test_auri_cv.py`

The working tree also has the uncommitted `.gitignore` change (ignores `external/` and `tools/cursor_bridge/LIVE_IMU/`) and the `tools/cursor_bridge/watch_cursor.py` change (takes a bridge-folder argument).

**Note:** many `clinician/` files are also modified. That is separate dashboard work (see the AGENTS.md entry from 19:41). Do not mix it into a W1 commit.

Measured result (Cursor brief 021): empty room, 15 s, port 8012.

| Measure | Value |
|---|---|
| Hub fps | 15.1–20.7, median 16.5 |
| Capture → hub latency | min 23 ms, median 44 ms, max 129 ms |
| CPU | worker about 73% of one core, hub about 3% |
| Arm angles | none given a number (correct) |

**Known bug:** in the empty room MediaPipe still emitted a head and both shoulders with visibility ≥ 0.5. The hub then showed a shrug index (0.59–1.07) and an "implausible shoulder width" flag. Required fix: when the engine quality is `UNAVAILABLE` or the arm landmarks are missing, shrug and every derived value are `null`. Cursor brief 022 asks for this, preferably in `auri_cv.py`, with a test.

### Wireless strap plan (IMU-001, read-only answer)
The full plan is in `tools/cursor_bridge/LIVE_IMU/from_cursor/001.md`. Main facts:
- Firmware already streams without USB: it waits at most 1.5 s for Serial, then advertises.
- The default partition table already has two 1.25 MB OTA slots. The C3 image is 600,112 bytes.
- Bootloader rollback is compiled in, but Arduino confirms a new image too early. `verifyRollbackLater()` must be overridden before OTA can be used.
- Only GPIO0–5 (D0–D3) wake the C3 from deep sleep. BOOT/GPIO9 cannot.

---

## 2. Hardware setup (one strap unit, XIAO ESP32-C3)

Pin map comes from `firmware/auri_strap/board.h`. The C3 map differs from the S3 map in handoff §6.1, so solder to `board.h`.

| XIAO pin | C3 GPIO | Use |
|---|---|---|
| D4 | 6 | I2C SDA → BNO085 SDA |
| D5 | 7 | I2C SCL → BNO085 SCL |
| D1 | 3 (ADC1) | battery divider midpoint (`PIN_BAT`) |
| D2 | 4 | BNO INT (`PIN_INT`, not read yet). Otherwise free for the phase D wake button |
| D3 | 5 | BNO RST, only if `AURI_BNO_RST_WIRED=1` |
| **D6** | **21** | **UART0 TX. Never use it for I2C.** Intermittent sensor faults on the bench came from this. |

Steps:
1. **BNO085:** 3V3, GND, SDA→D4, SCL→D5. Its address is 0x4A. I2C runs at 400 kHz (`AURI_I2C_HZ`).
2. **Battery (phase A):** 3.7 V LiPo (500 mAh on the BOM, with protection circuit) to the XIAO BAT pads, with a **slide switch in series with BAT+**. Check polarity before connecting.
   - Charge over USB-C only while the strap is off the body; the onboard charger runs at 380 mA.
   - Firmware cannot see charge state or turn the charger off.
3. **Battery divider (phase B):** 100 kΩ BAT+→D1, 100 kΩ D1→GND, 100 nF D1→GND. Then build with `-DAURI_HAS_BATTERY_DIVIDER=1`. Without the divider the hub must show the battery as *unavailable*, never 0.
4. **Wake button (phase D, optional):** momentary switch D2→GND with an external 10 kΩ pull-up to 3V3. Fit it only if BNO INT is not on D2.
5. **Current measurements:** put the meter **in series with the cell**. A USB meter measures 5 V bus current, which is a different quantity.

### Flashing
- Toolchain: arduino-cli 1.5.1, esp32 core 3.3.12.
- FQBN: `esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default`. `default` means USB CDC is enabled; `cdc` *disables* USB serial on both C3 and S3, so don't use it.
- S3 board: `esp32:esp32:XIAO_ESP32S3:CDCOnBoot=default`.
- Build-time options: `AURI_UNIT` (1 = ARM, 2 = TRUNK), `AURI_HAS_BATTERY_DIVIDER`, `AURI_BNO_RST_WIRED`, `AURI_TEST_PATTERN`, `AURI_PIN_SDA/SCL`, `AURI_I2C_HZ`.
- Upload with esptool option **`--before usb-reset`**. The default reset did not connect to board 2 while its firmware was printing.
- **Never open a COM port with DTR/RTS asserted** (it resets the board). With pyserial, set `.dtr = False` and `.rts = False` *before* `.open()`.
- Before overwriting a board that has unknown firmware, back it up first (`esptool read_flash 0 0x400000 …`).

---

## 3. Software setup (Windows laptop / station)

1. **Hub venv:** `hub/.venv`, Python 3.10.
   - For straps: `hub/.venv/Scripts/python.exe -m pip install -e "hub[straps]"`. This pulls `bleak>=0.22`.
2. **AURI-CV engine:** the teammate's repo at `external/AURIII`, pinned to commit **0011377**. It needs **Python 3.12** (it uses StrEnum), so it runs as a **separate worker process** with its own `external/AURIII/.venv`.
   - Do not import it into the hub.
   - Do not modify the teammate's code.
   - The hub finds the worker's interpreter through `auri_cv_python()` in `capture/auri_cv.py`.
3. **Web UI:** `cd web && npm install && npm run build`. The hub serves the built files at `/`.
4. **Norton TLS interception on this laptop:** package installs fail certificate checks. Use the PEM of the Windows trusted roots:
   - pip: `--cert C:/Users/laxme/AppData/Local/Temp/claude/D--medha/24fcde3e-1efc-406b-9483-754aacab6f6d/scratchpad/windows_roots.pem`. If the scratchpad is gone, re-export the roots.
   - uv: `--native-tls`, or `SSL_CERT_FILE` set to that PEM.
   - **Never** use `--trusted-host`, `verify=False` or anything else that turns verification off.
5. **Firmware Python:** `firmware/.venv` has `pyserial` installed (installed with `--cert`).

---

## 4. Running the station

Webcam (AURI-CV) plus straps. Open http://127.0.0.1:8012:
```
hub/.venv/Scripts/python.exe -m physiobuddy_hub run --webcam 0 --straps auto --motionnet off --port 8012
```
Run from `hub/`, or wherever the package is importable. The W1 test used this exact command without `--straps`. **[unverified]:** webcam and straps running together.

Flags (from `__main__.py`):

| Flag | Values |
|---|---|
| `--webcam [N]` | Laptop camera index (default 0), through the AURI-CV worker. Cannot be combined with `--bag` or `--sim`. |
| `--straps` | `off` (default), `auto`, or a BLE address list such as `14:63:93:BD:B4:7A[,…]`. |
| `--motionnet` | A model dir, or `off` (rules only). Feature-v2 models do not exist yet, so use `off`. |
| `--side right\|left` | Side of the affected shoulder. |
| `--sim` | Synthetic patient, for UI work. |
| `--debug-video` | Serves `/debug/stream.mjpg`. |
| `--dataset-dir` | Guided recording. **Scratch dir only, never `ml/data/real`.** |
| `--device cuda` | On the Jetson. |

Without a laptop: the RealSense D455f is the default picture source (`--pose auto`). On the Jetson the clinic station uses it, not the webcam.

### Strap calibration (hub REST)
1. Patient stands in the **N-pose** (arms by the sides, palms in): `POST /api/straps/calibrate/npose`
2. Patient does a **forward raise**. This fixes strap rotation about the limb: `POST /api/straps/calibrate/raise`
3. Check the state with `GET /api/straps/calibration`.

Camera rest calibration is a separate step: `POST /api/calibrate/rest`.

### What the dashboard shows (`web/src/main.js`)
- Everything comes from **`/ws/live`**, the per-frame state JSON stored in `ui.state`.
- **Three.js avatar** (`avatar.js`, `stage.js`, `anatomy.js`, `rom.js`):
  - It is a rigged human driven by the hub skeleton (keypoints are centred on the shoulder midpoint).
  - The ROM overlay reads `state.angles` (camera geometry) and `state.coach.target` / `form`.
  - It is drawn grey when `angles.elevation.value === null` (unavailable).
  - The anatomy highlights read `state.angles` and `state.angles.flags`.
- **Straps card** (`renderStraps`):
  - Hidden unless `state.straps` exists.
  - Shows `state.straps.devices` (rate, gaps, `battery_mv`, which is null without a divider) and `state.straps.calibration.state`.
  - Shows a comparison of camera angles (`state.angles`) against strap angles (`state.straps.angles`).
- The avatar and the coach follow the **camera**. Straps are shown next to it and fed to the network. The coach counts reps from the camera only.
- The **clinician dashboard** (`clinician/`, Vercel + Supabase) is a different app. The station does not upload sessions to it yet. That link is a TODO.

---

## 5. Data flow
```
BNO085 ──I2C──▶ XIAO C3 firmware (bno_lite, protocol v2, 37-byte packets @50/100 Hz)
   ──BLE notify──▶ hub straps/link.py StrapLink (bleak, reconnect with backoff)
   ──▶ straps/protocol.py decode ──▶ StrapCalibration (N-pose + forward raise)
   ──▶ core/strap_kin.py StrapKinematics ──▶ state.straps.angles
   └─▶ ml/features.py imu_features (FEATURE_VERSION 2, D_IMU 30) ──▶ MotionNetRunner.push(imu=…)  [advisory only]

Laptop webcam ──▶ tools/auri_cv_worker/worker.py (Py 3.12, MediaPipe PoseLandmarker + AURI-CV ShoulderAnalysisPipeline)
   ──one JSON line per frame on stdout──▶ hub capture/auri_cv.py WebcamSource.adapt_line
   ──▶ pipeline.py (SkeletonKinematics geometry → CameraAngles, coach rules, safety pause)
   ──▶ /ws/live state {angles, coach, straps, …} ──▶ web/ (three.js avatar, ROM overlay, Straps card)
```
The worker writes and sends no images. Degrees come only from geometry, in the camera pipeline or in StrapKinematics.

---

## 6. TODO, in order, to reach "fully functioning"
1. **Review and commit W1.** Read the diffs to the shared `pipeline.py` and `__main__.py`, run the tests and the web build, and commit only the W1 files. Leave `clinician/` out of that commit.
2. **Fix shrug and derived values to null when quality is `UNAVAILABLE`** (bug above). Done in brief 023 (137 tests pass).
3. **Live test with a person:** stand in front of the webcam and check that elevation, flexion and abduction move and that the avatar follows. Then wear board 2 on the upper arm, run N-pose + raise, and compare camera and strap angles in the Straps card. **[unverified]**
4. **Wireless phase A:** cell + slide switch on board 2; unplug USB; the hub connects and keeps 50 Hz with 0 gaps for a few minutes. *This is all the showcase needs.*
5. **Phase B:** the D1 divider and a `-DAURI_HAS_BATTERY_DIVIDER=1` build. The hub adds `battery_pct` and `battery_low`, both null when there is no divider. Pass: within about 50 mV of a meter.
6. **Phase C:** measure the voltage at which the board actually resets on the cell, then set the warn and stop levels (haptic pattern 3 to warn, stop streaming at the stop level). Do not ship 3.3 V as the cutoff before measuring.
7. **Phase D:** idle policy, if time allows: about 1 s advertising interval, sensor reports off, light sleep, optional D2 wake button. Protocol v3 adds STATUS type `0x07` and COMMAND `0x07` (see IMU-001 §Protocol).
8. **Phase E, signed BLE OTA:** after the showcase. Override `verifyRollbackLater()`, confirm the image only after a self-test, and prove that a bad image rolls back. **Never try it first on board 2, the only good board.**
9. **More strap units:** the full device has BNO085s on the upper arm, forearm and waist (AURI-TRUNK, `AURI_UNIT=2`).
   - Without a trunk strap, *true* elevation stays unavailable.
   - Boards 1 and 2 both stream; a third unit is needed for the waist (or forearm).
10. **Recorder strap data (Codex owns `recorder.py`):** save per-frame quaternion, gyro, gravity, host time and valid flag per sensor, plus the N-pose and raise samples. `pipeline.straps.snapshot(now_ms)` returns exactly that.
11. **Retrain PB-MotionNet** on feature v2 using real camera + strap sessions (`ml/`, Codex). Every older model is refused by the version check.
12. **`ml/validate_real.py`** must pass on held-out volunteers for that exact `model_version`. Until then the model stays advisory and display-only.
13. **Rename the leftovers from Physio Buddy / PB to Auri:**
    - the hub web UI title
    - the package name `physiobuddy_hub` (risky, do last)
    - the CAD lid labels `PB-ARM`
14. **Send station sessions to the clinician dashboard:** write to the shared Supabase `sessions` and `session_exercises` tables (schema in `clinician/supabase/schema.sql`). **[not designed yet]**
15. **Doc drift:** `PROTOCOL.md` labels the version field "(1)" but the firmware writes 2, and the sketch's header comment still says v1.

---

## 7. Non-negotiable rules (AGENTS.md / handoff §0)
- Degrees come from **geometry only**. The network judges form; it never outputs angles and is never consulted for safety.
- Missing data is **unavailable**, never 0. This covers battery and the shrug bug above.
- A trained model is **advisory** until `ml/validate_real.py` passes that exact `model_version` on held-out volunteers.
- Exercise targets and progression are **clinician-defined**.
- Run `hub/.venv/Scripts/python.exe -m pytest hub/tests ml/tests -q` before every commit, and `cd web && npm run build` after web changes.
- Commit small and often, and never rewrite history. Run `git status` / `git diff <file>` before editing a file; never overwrite another agent's uncommitted work.
- Ownership: Codex owns `ml/` and `hub/physiobuddy_hub/recorder.py`. Claude owns `web/`, 3D assets and `tools/blender/`.
  - Shared files: `pipeline.py`, `api/server.py`, `core/coach.py`, `__main__.py`. Check the diff first and commit right after editing.
- Test recordings go to a scratch `--dataset-dir`, never `ml/data/real`. No `git clone` into `ml/data/public`.
- Never print or commit secrets or `.env` files (`clinician/.env.local` is git-ignored).

---

## 8. Device stages (what "done" means, in order)
| Stage | What | Status |
|---|---|---|
| S0 | Pick board + sensor: XIAO ESP32-C3 + BNO085 at 0x4A, I2C D4/D5 | done |
| S1 | Firmware v2: own `bno_lite` driver, BLE protocol v2, 50/100 Hz, 0 gaps | done (board 2) |
| S2 | Release images + flashing guide (`firmware/release/`) | done |
| S3 | Hub ingest: `--straps`, StrapLink, calibration (N-pose, raise), strap angles, Straps card | done (A1, A2) |
| S4 | Webcam CV: AURI-CV worker -> `auri_cv.py` -> pipeline -> `/ws/live` -> three.js avatar | done, empty-room fix in 023; live person test pending |
| S5 | Camera + strap together on one station, strap on battery over BLE only | in progress (LIVE 024) |
| S6 | Wireless phase A: cell + slide switch, no USB | hardware pending |
| S7 | Phase B: battery divider on D1, `battery_pct`/`battery_low` | pending |
| S8 | Phase C: measured low-battery cutoff | pending |
| S9 | Phase D: idle power policy, protocol v3 | optional before 31 Oct |
| S10 | Phase E: signed BLE OTA with rollback | after showcase |
| S11 | Forearm + waist straps (3 units) so true elevation is available | pending |
| S12 | Recorder saves strap data; retrain feature-v2 model; `validate_real.py` | Codex |
| S13 | Station sessions -> clinician dashboard (Supabase) | not designed |

Board note (29 Oct): board 1 (USB 14:63:93:BD:AB:6C, BLE AB:6E) runs fine on another laptop with the same firmware. Its failure here was this laptop's USB/serial (opening COM7 resets it), not a solder fault. Verified over BLE in brief 024 (COM7 left closed).

## 9. How to work: the Claude <-> Cursor (Grok) bridge
Same method as this session. **Claude thinks, Cursor types.**

**Roles**
- **Claude** (the next agent): reads the code and docs, decides the plan, writes every brief, reviews every diff, runs tests, commits, talks to the user. Claude keeps its own token use low: it does not run long commands or edit large files itself when Cursor can.
- **Cursor agent** on Grok, highest effort and fast (this session ran `grok-4.7-high`; the cursor-bridge skill uses `grok-4.7-xhigh`, the extra-high one — check with `agent models` and use xhigh if listed). It executes: edits, builds, flashing (only with user OK), hardware tests, measurements. **It never commits.**

**Start (in its own terminal tab, one per work stream)**
```
& 'D:\medha\tools\cursor_bridge\LIVE\cursor_bridge.ps1' -Model grok-4.7-high -Workspace D:\medha
& 'D:\medha\tools\cursor_bridge\LIVE_IMU\cursor_bridge.ps1' -Model grok-4.7-high -Workspace D:\medha
```
`LIVE` = station, hub, CV. `LIVE_IMU` = wireless strap firmware. The `cursor-bridge` skill sets this up in any project.

**Loop**
1. Claude writes `tools/cursor_bridge/<LIVE>/to_cursor/NNN.md` (next number). A brief has: title with `(GO)` or `(read-only)`, context, numbered steps with pass criteria, rules, and "end with `STATUS:`".
2. Claude arms a watcher under Monitor. **Low token (default):** `hub/.venv/Scripts/python.exe tools/cursor_bridge/watch_done.py LIVE` prints only `DONE <msg> <STATUS line>` and `STUCK`. Full detail when debugging: `hub/.venv/Scripts/python.exe tools/cursor_bridge/watch_cursor.py LIVE` (re-arm when it expires; one line per user update, no running commentary).
3. Cursor answers in `from_cursor/NNN.md` and appends a dated line to `STATUS.md`. Claude reads the `STATUS.md` tail first (cheap), the full answer only when needed.
4. Claude reviews `git diff` of touched files, runs `hub/.venv/Scripts/python.exe -m pytest hub/tests ml/tests -q` and `cd web && npm run build`, then commits small commits with the AGENTS.md log entry.
5. To change a brief that Cursor has not started, overwrite or append to the same `NNN.md`; once started, send the next number.

**Rules every brief repeats**
- Never disable TLS checks or use `--trusted-host`; pip uses `--cert <windows_roots.pem>`, uv `--native-tls`.
- No flashing without the user's explicit OK; keep `firmware/backups/` untouched.
- Open serial ports with DTR/RTS false set before `open()`; flash the C3 with `--before usb-reset`.
- Stay out of `ml/` and `hub/physiobuddy_hub/recorder.py` (Codex).
- No secrets or `.env` contents in output or commits.
- Test sessions use a scratch `--dataset-dir`, never `ml/data/real`.

**Token discipline (the user asked for this)**
- Stop the bridges when idle; the user says when to resume.
- Give Cursor whole jobs ("do the full work") instead of single steps; Claude checks results, not every command.

**Open at hand-off (30 Oct ~19:00):** LIVE 041 (skeleton blinking) may still be running; LIVE_IMU idle after 002. User still has to: run SQL 038 then 039 on Supabase, solder cell/switch/divider for wireless phases A-C, add the web link to the Auth0 SPA app, decide on pushing the AURIMEDIC branch. Tasks 040-041/002 and the §11 plan are uncommitted here (earlier work is committed up to `1ffcefc`). A hub runs on port 8012.

## 10. Configuration (environment variables) — values are NOT in this file
Real values are sent privately by the project owner (chat / password manager), never in git or this document.

| Variable | Used by | Where it goes | Safe to share with a teammate? |
|---|---|---|---|
| `VITE_SUPABASE_URL` | clinician dashboard, Flutter app | `clinician/.env.local`, Vercel env, `--dart-define` | yes (public URL) |
| `VITE_SUPABASE_ANON_KEY` | dashboard, Flutter app | same | yes (publishable key; RLS protects data) |
| `VITE_AUTH0_DOMAIN` | dashboard, Flutter app | same | yes |
| `VITE_AUTH0_CLIENT_ID` | dashboard (SPA app) | same | yes; the Flutter app gets its own Native client id |
| `VERCEL_OIDC_TOKEN` | Vercel CLI only | written by `vercel` itself | **no** — never share, it is created per machine by `vercel login` |
| Supabase secret / service-role key (`sb_secret_…`) | nobody in the apps | — | **never** (bypasses row-level security). The one leaked earlier must be revoked. |

Setup: copy the four `VITE_` values into `clinician/.env.local` (git-ignored), `npm run dev` on 5175. The hub and the
strap firmware need no secrets.

## 11. Plan: three straps + camera, accurate angles, in the station AND the Flutter app
Goal: all three BNO085 straps (upper arm, forearm, trunk) + the camera feed one angle set that is **measured, checked
against a reference, and shown the same way** in the clinic station (hub + `web/`) and in the patient app
(`external/AURIMEDIC`). Everything below was read from the code on 30 Oct; items marked **[unverified]** were not run.

### 11.0 What exists today (so you don't rebuild it)
| Piece | State |
|---|---|
| Firmware | `firmware/auri_strap/`, protocol v2/v3 (`firmware/protocol/PROTOCOL.md`). **Unit A** (`AURI_UNIT=1`, BLE `AURI-ARM`) = one MCU with up to two BNO085 (sensor 0 @0x4A upper arm, sensor 1 @0x4B forearm). **Unit B** (`AURI_UNIT=2`, `AURI-TRUNK`) = trunk (sensor 2). Release images in `firmware/release/auri_strap_v0.1.0/` (`c3_arm`, `c3_trunk`, `s3_arm`). |
| What we actually own | Two **single-sensor C3 boards**: board 2 (BLE `14:63:93:BD:B4:7A`) and board 1 (`14:63:93:BD:AB:6E`). Both ship as unit 1 and both emit sensor 0, so the hub maps them by address: `--strap-slot ADDR=upper_arm,ADDR=forearm` (`hub/physiobuddy_hub/straps/link.py`, `_placed`). **No trunk strap yet.** |
| Hub ingest | `StrapLink` (own thread + loop, `straps/link.py`), `--straps off\|auto\|ADDR[,ADDR]`, calibration (`straps/calibrate.py`), angles (`core/strap_kin.py`), `imu_features` for PB-MotionNet. |
| Fusion | **None yet.** `pipeline.py` computes camera angles (`angles`) and strap angles (`straps.angles`) side by side in the live state; the coach counts reps from the **camera only**. Section 11.5 is the proposed fusion. |
| Tools | `tools/compare_cam_strap.py` (camera vs strap CSV + stats). The station's Straps card in `web/` shows link, calibration and a camera/strap comparison. |
| Patient app | `external/AURIMEDIC/app`, Flutter. Its `MotionEngine` (`lib/services/sensors.dart`) is a **simulated** stand-in ("until the CV engine is integrated", owned by Abdul) and the app "never shows angles to the user". Packages: `camera`, `permission_handler`, `auth0_flutter`, `supabase_flutter`, `webview_flutter`. **No BLE package, no pose package.** |

### 11.1 A - Hardware: three units on the body
| Strap | Unit / firmware | Placement | Pod axes |
|---|---|---|---|
| Upper arm | AURI-ARM, `AURI_UNIT=1`, sensor 0 | outer upper arm, mid-humerus, lid arrow toward the shoulder | X toward shoulder, Z out of the lid |
| Forearm | today a second AURI-ARM board (sensor 0, mapped by address); target = sensor 1 of unit A via Qwiic (`PB-FORE` pod) | dorsal forearm, arrow toward the wrist | X toward wrist, Z dorsal |
| Trunk | AURI-TRUNK, `AURI_UNIT=2`, sensor 2 | **chest band preferred** (a waist pod measures the pelvis and misses lower-back lean, `hardware/README.md`); pod on the front, arrow up | X up, Z anterior |

1. Flash each board from the release zip or arduino-cli: FQBN `esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default`, `--before usb-reset`, never DTR/RTS asserted, **only with the user's OK**. Trunk = the `c3_trunk` image (or `-DAURI_UNIT=2`). Back up before reflashing (`firmware/backups/`).
2. Label each pod (ARM / FORE / TRUNK) and mark the strap with a skin-safe pen so the pod returns to the same place; the pods slide on a dovetail rail with a click latch.
3. Strap snug enough that the pod does not rock (handoff section 6.3: sensors must be rigid on the segment), not so tight that it restricts circulation; no loose cable on the arm.
4. Charge cells off the body (the C3 charger runs at 380 mA while USB is plugged in). Cell + slide switch in series with BAT+. Battery % only after wireless phase B (section 6, steps 4-6).
5. Pass: each strap runs from its own cell, advertises, and survives a 15-minute wear with no pod shifting.

### 11.2 B - Connect and verify all three in the station
```bash
hub/.venv/Scripts/python.exe -m physiobuddy_hub run --webcam 0 --straps 14:63:93:BD:B4:7A,14:63:93:BD:AB:6E,<TRUNK_ADDR> --strap-slot 14:63:93:BD:B4:7A=upper_arm,14:63:93:BD:AB:6E=forearm --motionnet off --port 8012
```
The trunk pod needs no `--strap-slot`: its own sensor id 2 is already `trunk`. `--straps auto` scans and picks.
Check `GET http://127.0.0.1:8012/api/status` -> `straps.devices[]` and the Straps card. Per strap, over 30 s:

| Check | Pass |
|---|---|
| connected, `slot` correct | upper_arm / forearm / trunk |
| `packet_rate_hz` | 48-52 at 50 Hz |
| sequence gaps | 0 (`seq_gaps` stops growing) |
| `valid` | 100 % |
| quaternion norm | 1.000 +- 0.001 |
| gravity norm | 9.81 +- 0.3 m/s2 |
| `i2c_errors`, `notify_drops` | stable / 0 |
| `present` and `ok` | `[0]` / `[0]` (sensor really answering) |
| camera fps while all 3 stream | >= 18 (thread isolation proven for 2 straps, brief 029) |

Three links + camera on one laptop adapter is **[unverified]**; two links showed some gaps (brief 026). If gaps appear: lower the stream rate (`COMMAND 0x03`, 30-40 Hz is enough for angles), keep the large MTU (combined 37-byte packets), keep straps within 3 m, close other BLE apps, try a USB BLE 5 dongle. Reconnect: the hub retries with backoff capped at 10 s (brief 029); `POST /api/straps/reconnect` forces it; the "power-cycle board" note clears once the sensor reports present.

### 11.3 C - Calibration protocol (per set)
Why: each BNO085 game rotation vector has its **own arbitrary yaw** and there is no magnetometer, so yaw drifts (**2.48 deg/min** measured on board 1, brief 030) and the strap's rotation about the limb is unknown.
1. Patient stands upright, arms relaxed at the sides, palms to thighs, thumbs forward, looking ahead. Hub: `POST /api/straps/calibrate/npose` (collects 2 s). **Pass:** >= 50 unique samples per present strap and gyro peak <= 0.3 rad/s (`straps/calibrate.py`, `judge_npose`); the response lists samples per sensor and the reason on failure. Fixes: unknown yaw per sensor and mount tilt (from gravity).
2. One slow straight-arm **forward raise** (about 4 s), then `POST /api/straps/calibrate/raise`. **Pass:** the response lists the refined sensors (needs > 10 samples above 10 deg/s per strap); upper arm and forearm then have `forward_raise = true` and their angle quality becomes GOOD (otherwise LOW). Fixes: strap rotation about the limb axis (gravity cannot see it). A board lying still correctly rejects this step.
3. **Re-zero at the start of every exercise set** (step 1, 3 s) because of yaw drift. Any strap reconnect changes the link `generation` and clears the calibration: recalibrate after a reconnect.
4. `GET /api/straps/calibration` shows state, time and sensors. Trunk lean needs no raise (gravity only).

### 11.4 D - Angles: definitions and what each strap set gives
Same output type as the camera (`CameraAngles`), same thorax frame (X anterior, Y up, Z right), same thresholds (`core/skeleton_kin.py`): plane only at elevation >= 15 deg; rotation only at elevation <= 30 deg with elbow 60-120 deg and a horizontal forearm; ELBOW_DRIFT above 20 deg; TRUNK_LEAN_WARN 10 deg; APPARENT_TRUE_GAP above 10 deg.

| Angle | Strap computation | Needs | Camera |
|---|---|---|---|
| Apparent elevation | humerus vs world vertical (gravity in the upper-arm segment) | upper arm | yes |
| **True elevation** | humerus direction in the **trunk** frame vs down | upper arm + trunk | yes (drives the avatar) |
| Plane of elevation / movement name | atan2 of the humerus (z, x) in the thorax | upper arm + trunk, elevation >= 15 | partly (flexion and abduction names come from the webcam engine) |
| Elbow flexion | angle between humerus and forearm directions | upper arm + forearm + trunk | yes |
| External rotation | forearm direction atan2 at elbow about 90 | all three, elbow at the side | limited |
| Trunk lean sagittal / lateral | gravity in the trunk segment | trunk | yes |
| Shrug index | **unavailable from straps** (scapula) | camera only | yes |

Availability: upper arm alone -> apparent elevation only; + trunk -> true elevation, plane, trunk lean; + forearm -> elbow flexion, rotation. `z_sign` mirrors left and right so positive means the same clinical direction on both sides. A missing strap gives `unavailable` with a reason, never 0.

### 11.5 E - Fusion rules (proposal; nothing fuses automatically today)
1. **Degrees shown and recorded:** camera when its quality is GOOD (the network never outputs angles); the strap when the camera is UNAVAILABLE or LOW (occlusion, side-on, out of frame) and the strap set is calibrated (quality GOOD after the raise); otherwise "unavailable".
2. Both valid: show the camera value, show the strap value beside it, and flag `CAM_STRAP_DISAGREE` when the difference exceeds 8 deg for 1 s (proposed; tune after 11.6). Never average the two silently.
3. Rep counting stays camera-driven until strap-only counting is validated; strap angles may confirm a rep peak within 8 deg.
4. Straps own what the camera cannot see: forearm and elbow rotation, trunk lean when occluded. The camera owns shrug and anything that needs the scapula.
5. Every value carries its source and quality; a stale strap (`age_ms` above 250) is unavailable. PB-MotionNet stays advisory until `ml/validate_real.py` passes and never judges safety.

### 11.6 F - Accuracy validation protocol
Reference: a **fixed jig** (clamped protractor or a 3D-printed 0-180 deg arc) or a calibrated phone inclinometer on a rigid rod strapped to the arm; a goniometer for the elbow.
1. Set-up: all straps worn, N-pose + raise done, camera at 2 m with hips and wrist in view, bright even light.
2. Angles: forward elevation at 0, 30, 60, 90, 120, 150, 180 deg, then abduction at the same angles, elbow flexion at 30/60/90/120, trunk lean +-10 and +-20 deg. Hold each 3 s, **5 repeats**, two people if possible, plus one slow continuous raise.
3. Log: `hub/.venv/Scripts/python.exe tools/compare_cam_strap.py --seconds 60` (CSV: per-frame camera vs strap; stats: paired count, mean, mean abs diff, RMS, max, correlation, lag). Add the reference reading per hold in a side file.
4. Stats per angle: mean error, SD, RMS, max, n, for strap vs jig, camera vs jig and camera vs strap.
5. Proposed acceptance (confirm with the clinician): strap vs jig RMS <= 5 deg static and <= 8 deg moving; camera vs strap RMS <= 8 deg; a still board over 5 minutes drifts under 2 deg/min or is re-zeroed per set (board 1 measured 2.48 deg/min; it is yaw only, gravity-based angles such as elevation do not drift).
6. Report: `reports/accuracy_YYYYMMDD.md` with set-up photos, a table per angle, pass/fail, firmware and hub commit, who and when. Claim no more than these numbers.
Limits to state: no magnetometer, so rotation depends on the N-pose and drifts; strap rotation about the limb needs the raise; soft tissue under a strap adds a few degrees.

### 11.7 G - Data gathered in the station and sent on
1. Per frame in the live state: camera angles + quality, strap angles + quality, and raw per strap (quaternion, gyro, gravity, `seq`, host time, valid) from `pipeline.straps.snapshot(now_ms)`. **The recorder does not save strap data yet** (`hub/physiobuddy_hub/recorder.py`, owned by Codex; request logged in AGENTS.md). Record only with `--dataset-dir`, never into `ml/data/real` for tests (AGENTS.md rule 7), and only with consent.
2. Per exercise summary to Supabase (not built in the station yet, stage S13) into `sessions` / `session_exercises` (`clinician/supabase/schema.sql`): reps counted and rejected, peak and median degrees, pain, duration, source (`camera`, `straps` or `fused`), calibration time. **Null, not 0, when not measured** (`reps_rejected` is nullable since migration 20261030). Upload with the patient's token under RLS, never a service key.
3. Station-to-patient link: identify the patient by the `AU-` code or a QR so the session lands on the right `patients` row. **[not designed]**

### 11.8 H - Flutter app: the same three straps and the same maths
Today the phone has neither BLE nor pose. Plan:
1. **Packages:** `flutter_blue_plus` (or `flutter_reactive_ble`); keep `camera` and `permission_handler`; pose through Google ML Kit pose detection (`google_mlkit_pose_detection`) **or** a MediaPipe Tasks plugin, decided with Abdul (owner of the on-phone engine) behind the existing `MotionEngine` interface. **[unverified: compare its accuracy with the hub's AURI-CV]**
2. **Android 12+** (`AndroidManifest.xml`): `BLUETOOTH_SCAN` with `android:usesPermissionFlags="neverForLocation"`, `BLUETOOTH_CONNECT`, and `ACCESS_FINE_LOCATION` with `maxSdkVersion="30"`; request at runtime through `permission_handler`. **iOS** `Info.plist`: `NSBluetoothAlwaysUsageDescription`. Auth0 and Supabase setup stays as in `docs/PATIENT_APP_FLUTTER.md`.
3. **Connect three peripherals:** scan for service `3c3ff578-acd0-46f5-a868-3ef18783e0b1` (names `AURI-ARM` twice today, `AURI-TRUNK`); store address -> slot in `shared_preferences` (the same idea as `--strap-slot`); request a large MTU (247 on Android) so the 37-byte combined packet is used; subscribe to IMU_DATA and STATUS (and RAW_DATA when the MTU is small); write COMMAND `0x03` (rate), `0x04` (start) and the `0x06` time ping. Reconnect with backoff, never on the UI thread. Android phones usually allow about 7 links, so 3 is fine **[unverified]**.
4. **Dart modules** (`lib/strap/`):
   - `protocol.dart`: port of `hub/physiobuddy_hub/straps/protocol.py` (IMU 17 B, combined 37 B, RAW 20 B, STATUS 16 B + power 0x07; little-endian; Q14 quaternion, Q10 gyro, Q8 gravity).
   - `strap_link.dart`: scan, connect, reconnect, streams.
   - `strap_kin.dart`: port of `core/strap_kin.py` (`fromNpose`, `refineWithForwardRaise`, `compute`).
   - `calibration.dart`: N-pose and raise screens logic.
   - `fusion.dart`: the rules of 11.5.
   - `angles.dart`: value / quality / unavailable-reason model.
   - **Golden vectors:** export JSON from Python (packet bytes -> fields, quaternions -> angles, in the style of `hub/tests/test_strap_kin.py`) into `external/AURIMEDIC/app/test/fixtures/`; the Dart output must match within 0.1 deg.
5. **Screens:** the app already has bands/setup screens (`lib/screens`, "bands" strings): extend them with the three-strap checklist, battery (`battery_mv` and percent after phase B, low-battery warning), calibration (N-pose 3 s, raise) and a live per-exercise readout. The app currently never shows angles to the patient: that is a team design choice, so confirm before adding any number to the patient UI. The clinician always sees angles.
6. **Saving:** reps and angles into `sessions` / `session_exercises` through `supabase_backend.dart` with nulls for unmeasured; reuse `sync_queue.dart` for offline; no raw video leaves the phone.
7. **Limits:** iOS and Android restrict BLE in the background (keep the session screen on, use a wake lock); phone BLE throughput is lower than a laptop's **[unverified]**; yaw drift means a re-zero per set on the phone too.
8. **Pass:** the Dart port reproduces the golden vectors; three straps stream >= 45 Hz with 0 gaps on a phone for 5 minutes; phone angles vs the hub (same arm) within 5 deg RMS; a session with straps off still works (camera only), and with the camera denied the straps alone give the angles of 11.4.

### 11.9 I - Milestones (each fits one Cursor brief; Claude reviews, Cursor executes, see section 9)
| # | Milestone | Depends on | Your hardware or decision | Pass |
|---|---|---|---|---|
| M1 | Commit the uncommitted work (briefs 033-041) after tests | - | OK to commit | clean tree, 141+ tests |
| M2 | Third strap: trunk unit built and flashed, shows as `trunk` in the hub | M1 | build the trunk pod, OK to flash | Straps card shows 3 and passes 11.2 |
| M3 | Distinct strap identity (own name/unit for the forearm board, or keep address mapping) and a 3-link + camera run | M2 | - | no gaps at 50 Hz, camera >= 18 fps |
| M4 | Guided calibration in the station (N-pose and raise buttons with pass/fail text) | M2 | a person to stand | calibration view shows both steps passed |
| M5 | Accuracy jig and validation session, report in `reports/` | M4 | build or borrow a jig, 2 volunteers | thresholds of 11.6 met or documented |
| M6 | Fusion layer, disagreement flag, UI source badge | M5 | clinician OK on thresholds | camera / strap / fused shown, never invented |
| M7 | Station -> Supabase session upload (S13) and recorder strap data (Codex) | M1 | consent wording | session visible on the clinician dashboard |
| M8 | Dart protocol + kinematics port with golden-vector tests | M2 | - | Dart equals Python within 0.1 deg |
| M9 | Flutter BLE: 3 straps on a phone, calibration screens, battery | M8 | Android phone with USB debugging | 5 min, 0 gaps, 45+ Hz |
| M10 | Phone camera pose engine, fusion and saving angles; release APK | M9, M6 | decision on showing angles to patients | phone vs hub within 5 deg RMS, session saved with nulls |
