# ml/: movement judging (PB-MotionNet) and baselines

Angles in degrees always come from geometry in the hub (`SkeletonKinematics`). Nothing here outputs degrees.
The network only judges: which exercise (or "unknown"), rep phase, correct form, and compensation.

## Workflow
```bash
hub/.venv/Scripts/python.exe ml/fetch_public.py                                  # public data -> ml/data/public
hub/.venv/Scripts/python.exe ml/run_spar_baseline.py                             # Lee 2024 on real SPAR data
hub/.venv/Scripts/python.exe ml/train_motionnet.py --public --folds 5            # pre-train + subject-grouped CV
hub/.venv/Scripts/python.exe ml/train_motionnet.py --public --real ml/data/real  # + our volunteers (LOSO)
hub/.venv/Scripts/python.exe ml/validate_real.py --real ml/data/real             # gate before the hub may use it
hub/.venv/Scripts/python.exe ml/run_benchmark.py --public --real ml/data/real    # rules vs Lee vs RF vs MotionNet
hub/.venv/Scripts/python.exe -m pytest ml/tests -q
```
`--synthetic N` exists on the training and benchmark scripts for **code-path checks only**: use N >= 6. With fewer
people, each fold trains on almost no one and the numbers mean nothing.

## Data sources
| Source | Inputs | Labels | Licence |
|---|---|---|---|
| SPAR (Burns et al. 2018) | Wrist IMU, 20 people, both arms | 7 shoulder exercises (rows map to "unknown") | GPL-3.0 |
| IntelliRehabDS (Miron et al. 2021) | Kinect v2 skeleton, 29 people (15 patients) | Gesture + correct/incorrect per rep | CC BY 4.0 |
| REHAB24-6 (Cernek et al. 2024) | Motion-capture skeleton, 10 people | Arm abduction + correctness; other exercises map to "unknown" | Non-commercial research |
| Team recordings (`ml/data/real`) | RealSense + RTMPose skeleton (+ straps when worn) | Guided blocks, per-attempt outcome (counted / rejected / incomplete / paused) | Volunteer consent |

## Honest evaluation rules (enforced in `pbml/train.py`)
- Folds are split **by person** (LOSO or GroupKFold); an assertion blocks any person in both train and test.
- Only **original** windows of held-out people are scored. Augmented copies are training data only.
- The "unknown" energy cutoff is tuned on **calibration people held out** from each fold's training set,
  but only when at least 3 people of that source remain to train on. Otherwise that input mode is tuned in-sample
  at the looser 99% quantile, and the report's `calibration` entry says so.
- Recordings made before per-attempt labels existed are skipped (rejected attempts would be mislabelled).

## When the hub may use a model
`train_motionnet.py` exports to `hub/models/motionnet/`. Every export starts **advisory only**: the hub shows the
network's opinion but it cannot reject reps, add issues or switch exercises. `validate_real.py` replays held-out
volunteers (never ones the model trained or calibrated on) through the hub's own runner and coach rules; only a pass
for that exact `model_version` turns hybrid coaching on. The strap branch stays off until recordings with straps pass.
Run the hub with `--motionnet off` for rules-only coaching.

## Results so far
- Lee 2024 method on real SPAR data (20 people): random split 90.2%, leave-one-person-out 84.9% (worst person 67.9%).
  Main confusions: internal vs external rotation, side vs forward raise. Report: `reports/spar_lee2024.json`.
- PB-MotionNet: no public-data result yet. All earlier `motionnet_cv_*` and `benchmark_*` reports are synthetic
  code-path checks.

## Known limitations
- The skeleton branch has only seen Kinect / motion-capture skeletons, never RealSense + RTMPose.
- No public source records camera and straps together, so fused performance is unmeasured until team recordings.
- The strap branch has only seen a wrist-worn Apple Watch, not BNO085 straps on arm, forearm and chest.
- `pbml/exercises.py` holds the 11-class Lee 2024 label set used only by the baseline; PB-MotionNet uses the six
  classes in `physiobuddy_hub/ml/features.py`.
