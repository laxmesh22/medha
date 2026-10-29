# Agent handoff: Auri device + webcam CV → clinic station dashboard

Written 2026-10-29 for the next agent. Showcase: **31 Oct 2026, IIT Bombay**. Read `agenthandoff.md` (rules, maths)
and `AGENTS.md` (working rules, log) first. Items marked **[unverified]** were not tested on hardware.

---

> **For the person continuing the device (29–30 Oct hand-over).** This file is the whole story of the device and
> station work so far: what exists, what was measured, what is broken, what to do next, and how we work (Claude
> plans and reviews, Cursor/Grok executes, §9). Start with §0, then §6 (TODO) and §8 (stages). Nothing from briefs
> 021–033 is committed yet: commit it first (§6 step 1) so your work starts from a clean tree.


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
- 033 (running): user sees the Vision preview as laggy/buggy although the hub reports ~30 fps. Brief: measure
  drawn fps and end-to-end delay in the browser, draw image + skeleton from the same frame id with
  requestAnimationFrame, drop late frames, fix aspect/mirror; Straps card shows "off / searching" clearly.
  Both straps had gone to 0 Hz (batteries flat or switched off), camera unaffected.

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

**Open at hand-off:** LIVE 033 (Vision preview lag, Straps off-state). 021–032 done but not committed. LIVE_IMU: only 001 answered.

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
