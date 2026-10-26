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
- (empty)

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

Proposed split until the user says otherwise: **Codex** owns `ml/` and `hub/physiobuddy_hub/recorder.py`;
**Claude** owns `web/`, the 3D assets and `tools/blender/`. Shared files (`hub/physiobuddy_hub/pipeline.py`,
`api/server.py`, `core/coach.py`, `__main__.py`): check `git diff` first and commit right after editing.
