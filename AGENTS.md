# Notes for AI agents working in this repo

Two agents have been editing this repo at the same time (a Claude Code session and an OpenAI Codex session).
Read this file before you start, and add to the log at the bottom when you finish a piece of work.

Project context: `agenthandoff.md` (rules, hardware, maths), then `jetson_realsense_ai_design.md` (architecture,
schedule). Showcase: 31 Oct 2026, IIT Bombay. ML specifics: `ml/README.md`.

## Working rules
1. **Commit early and often** in small commits with clear messages. Baseline is `e5007e4`; never rewrite history.
2. **Before editing a file, run `git status` / `git diff <file>`.** If someone else has uncommitted changes in it,
   commit or ask the user first. Do not overwrite another agent's work.
3. **Say what you are working on** in the "Now working on" list below, and clear it when done.
4. Keep the project's non-negotiable rules (handoff §0):
   - Degrees come from geometry only. The network judges; it never outputs angles and is never consulted for safety.
   - Missing data is "unavailable", never 0.
   - A trained model is advisory until `ml/validate_real.py` passes that exact `model_version` on held-out volunteers.
   - Exercise targets and progression are clinician-defined.
5. Run `hub/.venv/Scripts/python.exe -m pytest hub/tests ml/tests -q` before committing. Rebuild the UI with
   `cd web && npm run build` after web changes.
6. Do not `git clone` dataset repos into `ml/data/public`: `ml/fetch_public.py` downloads only the needed files.
7. Test recording sessions go to a scratch `--dataset-dir`, never `ml/data/real` (that folder is training data).

## Now working on
- 30 Oct, Claude Code + Cursor (bridge LIVE brief 042): connecting and calibrating three straps. Files: `hub/physiobuddy_hub/straps/*`, `pipeline.py`, `api/server.py`, `core/strap_kin.py`, `web/src/main.js`, `tools/identify_straps.py`, `tools/calibrate_straps.py`. **Codex: stay out of these until this line is cleared**; `ml/` and `recorder.py` remain yours.

## Log
### 2026-10-14 22:57 · Claude Code (session "Agent handoff with OpenCV gesture tracking")
Reviewed Codex's work since 21:16 (recorder, safety pause, dataset loaders, PB-MotionNet, validate_real, advisory
gating). It is solid, and it already fixed the review points raised earlier: augmented windows are no longer scored,
the unknown cutoff is tuned on held-out people, attempts are labelled counted/rejected/incomplete/paused, unvalidated
models are display-only.

Changed after Codex's last edit (22:45):
- `ml/pbml/train.py`: **calibration guard.** `calibration_split` holds people out only when at least
  `MIN_FIT_SUBJECTS = 3` of that source remain to train on. Otherwise `fit_and_calibrate` tunes that mode in-sample
  at the looser `IN_SAMPLE_KEEP = 0.99` quantile. `fit_and_calibrate` now returns
  `(model, thr, {"held_out": [...], "in_sample_modes": [...]})`, and `grouped_cv` reports it under `"calibration"`.
  Why: `benchmark_20261014-2244` used 4 synthetic people with 2 folds, so each fold trained on **one** person and
  PB-MotionNet fell to chance (0.19 accuracy, 0 form sensitivity).
- `ml/train_motionnet.py`: export keeps `calibration_subjects` a **plain list** (`validate_real.py` excludes those
  volunteers; a dict would silently stop excluding them) and adds `calibration_in_sample_modes`.
- `ml/tests/test_motionnet.py`: new test for the guard. `ml/README.md`: rewritten for the current pipeline.
- Baseline commit `e5007e4`, `.gitattributes` (LF line endings), this file.

For Codex:
- Your public run started 22:44 loaded the pre-guard code. With 10-29 people per source that is fine; let it finish.
- Please re-run `ml/run_benchmark.py --synthetic 6 --epochs 6` (or larger) after it, so the collapsed
  `benchmark_20261014-2244` is replaced by a meaningful code-path check.
- Your test station on port 8765 (`--dataset-dir %TEMP%/pb-rec-check`) has been running since 21:37; stop it when done.
- `ml/data/public/SPAR` holds ~8.5 GB that nothing reads (`.git` 1.6 GB, `lbp_csv` 6.9 GB). Only `csv/` is needed.
  The user has been told; do not add more clones.

### 2026-10-14 23:05 · Claude Code: diagnostic result
Confirms the collapse was only the 4-person setup, not a bug. 10 synthetic people, GroupKFold(5), 8 epochs,
2 calibration people held out per fold, scored on original windows of held-out people (synthetic: code-path only):

| Mode | Accuracy | Unknown rejected | Known falsely rejected | Form sensitivity / specificity |
|---|---|---|---|---|
| skeleton | 0.952 | 0.972 | 0.048 | 0.887 / 0.994 |
| imu | 0.681 | 0.837 | 0.067 | 0.197 / 0.972 |
| fused | 0.954 | 1.000 | 0.048 | 0.894 / 0.999 |

The IMU branch is clearly weaker at judging form (0.20 sensitivity); worth a look when real strap data exists.

### 2026-10-26 · Claude Code: CAD review of `Cobra+Radio+Clip_stls.zip`
New `tools/cad/`: `stl_report.py` (size, bodies, watertight, volume, PLA grams), `render_stl.py` (Blender 4-view
render with 10 mm grid), `stl_section.py` (scaled cross-section). The supplied part is a generic walkie-talkie
belt clip: one watertight body 69.2 x 34.7 x 30.9 mm, ~22 g PLA, 3 mm back plate, 2.8 mm sprung tongue with an
~8 mm grip gap, and a 40 x 13.7 mm slide-rail lug with latch window. It is not an enclosure for the electronics, and
a spring clip on a strap lets the IMU rock (handoff §6.3: sensors must be rigid on the segment). Recommendation given
to the user: keep the slide-rail quick-release idea, not the clip. Raw files stay in `assets_src/cad/` (ignored).

### 2026-10-26 · Claude Code: wearable pod CAD and on-body video
- `hardware/cad/physio_pod.py` (CadQuery): upper-arm pod (BNO085, XIAO ESP32-S3, coin motor, deck with LiPo +
  DRV2605L), forearm pod (BNO085 only, Qwiic to the arm pod), trunk pod, and curved strap bases for upper arm,
  forearm, chest and waist (40 mm belt). Every pod slides onto every base on the same dovetail "PB-rail" with a
  click latch, so the sensor returns to the same place and orientation each session. Fit check passes; all STLs are
  watertight single bodies. Outputs in `hardware/cad/out/` (STEP, STL, GLB, SLDPRT via
  `tools/cad/solidworks_convert.py`). Manufacturer STEP files dropped in `hardware/cad/vendor/` are picked up
  automatically (names in its README); the user is fetching them from GrabCAD.
- The user asked for the trunk band on the **waist**, not the chest. A waist pod measures the pelvis, so strap-only
  trunk lean is less accurate; the camera still measures trunk lean. Documented in `hardware/README.md`.
- `tools/blender/device_on_avatar.py`: the Rocketbox avatar wearing all three units (bone-parented, straps
  shrink-wrapped to the skin, Qwiic cable on hooks), flexion / abduction / external-rotation shots, product
  explode-assemble shot, captions. Output `hardware/renders/physio_buddy_device.mp4` (19 s, 1080p).
  Blender 5.x note: set `image_settings.media_type = "VIDEO"` before `file_format = "FFMPEG"`.
- Fit now checked against real vendor models (Adafruit BNO085 4754 and DRV2605L 2305, Seeed XIAO ESP32-S3);
  the XIAO is 4.5 mm tall, so the arm pod is 23.1 mm. Vendor STEPs are git-ignored (see `hardware/cad/vendor/`).
- No changes to `hub/` or `ml/`.

### 2026-10-26 23:35 · Claude Code: device film v2
`hardware/renders/physio_buddy_film_v2.mp4` (35 s, 1080p, music). Pipeline in `video/README.md`:
`tools/blender/device_film.py` (Cycles shots + per-frame tracking JSON with skeleton-measured arm angles) ->
`video/scripts/encode_footage.py` -> `tools/audio/make_soundtrack.py` (synthesized, licence-clean) -> Remotion in
`video/`. Lessons: on this laptop Cycles must use the OptiX denoiser (OIDN picked the Intel iGPU: 35 s/frame); avatar
shots keep their timeline frame numbers (encoder passes `-start_number`); `--frames a b` re-renders part of a shot.
No changes to hub/, ml/ or web/.

### 2026-10-27 01:00 · Claude Code: assembly guide video
`hardware/renders/physio_buddy_assembly_guide.mp4` (2:29, 19 steps; `_mobile.mp4` is a 14 MB copy). Blender clips
from `tools/blender/assembly_guide.py` (one clip per build step, CAD-accurate: the design has no screws), edited in
Remotion (`video/src/guide/`: step panels, animated wiring diagram from agenthandoff.md section 6, callouts).
Regenerate: render the clips, `video/scripts/encode_footage.py --guide`, `tools/audio/make_soundtrack.py --guide 151`,
then `npx remotion render AssemblyGuide`. Guide stills, footage and the long music bed are git-ignored.

### 2026-10-27 02:30 · Claude Code: strap features v2 (user asked me to do this in ml/)
The strap branch was trained on one wrist IMU (synthetic + SPAR), but the device has BNO085s on the upper arm,
forearm and waist, and the faults we judge (trunk lean, elbow drift) happen at the trunk and shoulder. Changes:
- **New `hub/physiobuddy_hub/core/strap_kin.py`**: quaternions -> `CameraAngles`, with the same thorax frame, formulas,
  thresholds and flags as `SkeletonKinematics`, so the coach's rule checks work on straps unchanged.
  `StrapCalibration.from_npose` + `refine_with_forward_raise` (the raise fixes strap rotation about the limb).
  Shrug is unavailable from straps.
- **`hub/physiobuddy_hub/ml/features.py`**: `FEATURE_VERSION = 2`. `IMU_SENSORS = (upper_arm, forearm, trunk)`, and
  `D_IMU` goes 18 -> 30: strap kin values (same 9 as the skeleton block, via new `kin_vector`), per-strap rate and
  gravity in segment axes, present flags. `D_IN` goes 56 -> 68. `imu_features` now takes
  `{"angles", "gyro", "up"}`. `motionnet_infer` refuses models whose `feature_schema.version` differs.
  **Every existing model must be retrained.**
- **New `ml/pbml/straps.py`**: virtual straps from skeletons (misplacement up to 15 deg, tilt, yaw references, noise,
  bias), calibrated through the real `StrapCalibration`.
  - `synth_skeleton.make_sequence` returns `(seq, segs)`, not `(seq, acc, gyro)`.
  - `from_skeleton_sequence(..., straps=frames)` replaces `imu=`.
  - `train.augmented_copies` re-derives straps from the augmented motion (the ROM-restricted copies used to keep
    full-range IMU).
  - `from_imu_segment` puts SPAR's watch into the forearm slot.
- Tests: `hub/tests/test_strap_kin.py` (5) and `test_virtual_straps_track_the_camera_angles`. 117 tests pass.
- Synthetic diagnostic (10 people, GroupKFold 5, 8 epochs; `reports/motionnet_cv_20261027-0207.json`):
  - strap accuracy 0.681 -> 0.931
  - faulty-rep sensitivity 0.197 -> 0.609 (shrug stays invisible to the straps)
  - unknown rejection 0.837 -> 1.000
  - skeleton and fused unchanged at about 0.95
  - Still a code-path check, not real performance.

For Codex:
- The recorder does not store strap data yet. When the BLE firmware lands it should save per-frame quaternions and
  gyro per strap, plus the N-pose and forward-raise samples, so real sessions use the same `StrapCalibration`.
- Your public run (`reports/motionnet_cv_20261014-2357.json`, untracked) used feature v1. Re-run it to compare.

### 2026-10-28 · Claude Code: clinician (physio) dashboard
The team assigned the user (with Aditya Harbuda) the doctor side: physio onboarding with a unique referral code,
patients link with it from the patient app (Adi), prescribe exercises, see daily progress. Supabase for data.
- New `clinician/`: Vite + React + TypeScript, `npm run dev` on port 5175. Runs on built-in demo data when
  `VITE_SUPABASE_URL` is unset.
- `clinician/supabase/schema.sql` is the **shared schema for the patient app too**: clinicians, patients,
  care_links, exercises, versioned care_plans + plan_items, sessions + session_exercises, row-level security, and the
  RPCs `create_clinician_profile`, `regenerate_referral_code`, `link_patient_with_code` and `publish_care_plan`.
  The data contract is in `clinician/README.md`.
- Pages:
  - overview (alerts first)
  - patients list
  - patient detail: progress charts, care-plan editor with version history, sessions, medical info,
    messages placeholder
  - profile with referral code + QR
  - exercise library
- Messaging is parked, as the team asked.
- Brand hex values are provisional (`--brand-*` in `src/styles.css`) until the team sends the exact codes.
- No changes to hub/, ml/ or web/.

### 2026-10-28 · Claude Code: dashboard video consults + shared preview
- Video consults: each care link has its own `video_room`, and booked or started calls are stored in `video_calls`
  (schema + RLS added to `clinician/supabase/schema.sql`). Calls open on Jitsi Meet in a new tab. Embedded meet.jit.si
  calls are cut off after 5 minutes, and Artifact pages cannot use WebRTC. `VITE_VIDEO_BASE_URL` switches provider.
- Patient app (Adi) should show booked calls and open `https://meet.jit.si/<video_room>`: see `clinician/README.md`.
- `npm run artifact` builds a single-page demo (memory router, forced demo data). Published for the team at
  https://claude.ai/artifact/AM5xVZhwJXXYh9MBM2YV4q (private until the owner shares it).

### 2026-10-28 · Claude Code: Auth0 + Google sign-in, new doctor sign-up
- `clinician/`: Auth0 SPA sign-in (Google via the `google-oauth2` connection, email via Auth0's hosted page). It
  falls back to Supabase auth (email + Google) when Auth0 is not configured. New `/signup` page with 3 steps
  (account, professional details, confirm), ending with the referral code.
- **Schema change** (`clinician/supabase/schema.sql`, not yet run anywhere):
  - People are identified by the token's `sub` via `current_sub()`, `my_clinician_id()` and `my_patient_id()`.
  - `clinicians` and `patients` have their own uuid ids plus `auth_sub`, and no longer reference `auth.users`.
  - Auth0 subs are not UUIDs, so `auth.uid()` is gone.
  - `create_clinician_profile` now takes one jsonb argument.
  - New doctor fields: specialization, city, council, years_experience, email, verification_status.
- Patient app (Adi): insert the `patients` row after sign-in (`auth_sub` defaults from the token). The Auth0 setup
  steps are in `clinician/README.md`.

### 2026-10-28 · Claude Code: device renamed to Auri, dashboard intro video
- **The device is now called "Auri"** (user's decision). The clinician dashboard uses it everywhere: referral codes
  are `AU-xxxxxx`, video rooms `au-…`, consult subject "Auri consult". The hub web UI, the earlier films, the CAD lid
  labels (`PB-ARM`…) and the hub package name still say Physio Buddy / PB; not renamed yet.
- `hardware/renders/auri_dashboard_intro.mp4` (54 s, 1080p, music): walkthrough of the dashboard (sign-up with
  Google, referral code, overview, patients, range-of-motion charts, versioned care plan, video consult).
  Remotion composition `AuriIntro` (`video/src/intro/`). Screens are captured from the demo build with
  `video/scripts/capture_dashboard.mjs` (dev server on 5175 + chrome-headless-shell); music
  `tools/audio/make_soundtrack.py --intro 58`.

### 2026-10-28 · Claude Code: dashboard live on Supabase + Auth0 + Vercel, logo
- `clinician/.env.local` (git-ignored) points at the team's Supabase project and Auth0 tenant
  `dev-4cz1sir5jj78abm1.us.auth0.com`; `schema.sql` has been run there. Deployed with the Vercel CLI (project
  `auri-clinician`, same four VITE_ vars set in Vercel): https://auri-clinician.vercel.app. Redeploy:
  `cd clinician && npx vercel deploy --prod`.
- Fixed: React StrictMode exchanged the Auth0 code twice ("Invalid state" -> "Could not load data"). Signing in without
  a doctor profile now shows a red "No account found" banner on sign-up.
- Logo from the brand sheet (`src/components/Logo.tsx`, `public/favicon.svg`, app icons). Brand colours are final:
  Deep Teal #0A4A4F, Off-White #F5F2EA.
- Branch `design-language` (worktree `.claude/worktrees/design-language`) holds the separate restyle to Aditya's
  design language; it does not have the logo yet.

### 2026-10-29 · Claude Code (+ Cursor agent via tools/cursor_bridge): strap firmware and hub ingest
- **Firmware** `firmware/` (commits de23b09 → 9510dd4): XIAO ESP32-C3/S3, own multi-instance BNO08x driver
  (`src/bno_lite`), BLE protocol **v2** (`firmware/protocol/PROTOCOL.md`; 37-byte IMU+gyro+gravity packets). Tested on
  hardware: 50 and 100 Hz with 0 sequence gaps. Release zip `firmware/release/` (git-ignored). Bench note: never put I2C
  on D6/GPIO21 on the C3.
- **Hub** `hub/physiobuddy_hub/straps/` (ba8d4b6, 16258cb): `run --straps off|auto|ADDR` (default off). StrapLink
  (bleak), calibration endpoints, `StrapKinematics` angles in the state, and the `imu_features` block passed to
  `MotionNetRunner.push(imu=...)`. The coach still counts from the camera only.

For Codex (owner of `ml/` and `recorder.py`):
- The recorder does not save strap data yet. Please record per frame, when `pipeline.straps` is on: per sensor the
  quaternion (w,x,y,z), gyro (rad/s, sensor axes), gravity (m/s²), sample host time and valid flag, plus the N-pose and
  forward-raise samples used for `StrapCalibration`. `pipeline.straps.snapshot(now_ms)` returns exactly that.
- Then a feature-v2 PB-MotionNet can be trained on real strap + camera sessions; until `ml/validate_real.py` passes
  it stays advisory.

Proposed split until the user says otherwise: **Codex** owns `ml/` and `hub/physiobuddy_hub/recorder.py`;
**Claude** owns `web/`, the 3D assets and `tools/blender/`. Shared files (`hub/physiobuddy_hub/pipeline.py`,
`api/server.py`, `core/coach.py`, `__main__.py`): check `git diff` first and commit right after editing.

### 2026-10-29 19:41 · Cursor: clinician dashboard notes from Laxmesh
Signup, emergency, attention page, static profile. Not committed, not deployed.
- Smaller logo (sidebar 38→28, sign-in panel 52→36).
- Sign-in panel line 3 mentions who needs attention; line 5 is an emergency call with the patient. "Secure sign-in by Auth0" removed.
- Create account goes to Google and then the form. The Auth0 return to `/signup` does not query `clinicians` first. No "No account found" banner.
- Council is a dropdown (statutory PT councils plus NCAHP state allied councils). Registration number is labelled licence number. "Years of experience" is "Practising since" (a year); stored `years_experience` is still the year-count so the 0–70 check holds.
- Terms at `/terms`, required on the confirm step.
- `/attention` for patients who are not on track. Overview "Video calls" is now Emergency (high or rising pain, call the patient, not an ambulance). Patient tab renamed the same way; follow-ups still use `video_calls`.
- "No plan" is no longer an alert or a filter. Empty plan says "Set exercises". Profile is read-only (copy code stays; regenerate and the edit form are gone).

### 2026-10-31 · Claude Code: strap figure mirror fix + waist analysis
- `web/src/main.js`: in mirror mode (the default) the strap pose flipped x but still drove the patient's own arm bone,
  so a side raise swept across the chest and the ROM arc sat on the other arm. It now moves to the other arm, like
  `mirrorKeypoints`. Not checked live (needs a calibrated phone feed).
- Open: the waist band's forward direction is never calibrated. `_M["trunk"]` assumes the pod on the front of the
  belt, arrow up; the N-pose fixes only up and the raise fixes only the arms. The waist is now B4:7A (an arm board),
  so trunk lean and chest tilt can come out sideways or reversed. Proposed: a short lean-forward calibration step.
- `test_auri_cv::test_pipeline_reads_the_worker_skeleton_and_skips_depth_lift` and
  `test_straps::test_straps_off_leaves_the_state_without_straps` fail since straps are always published (STATUS 115).
