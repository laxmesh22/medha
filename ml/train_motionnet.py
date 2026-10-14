"""Train PB-MotionNet, evaluate it per subject, export ONNX for the hub.

    hub/.venv/Scripts/python.exe ml/train_motionnet.py --synthetic 8 --epochs 8      # code-path check only
    hub/.venv/Scripts/python.exe ml/train_motionnet.py --public --folds 5             # pre-train on public data
    hub/.venv/Scripts/python.exe ml/train_motionnet.py --public --real ml/data/real   # + team recordings (LOSO)

Evaluation is subject-grouped: LOSO by default, ``--folds K`` for GroupKFold on large public sets, ``--no-cv``
to skip. Only original (non-augmented) windows of held-out subjects are scored. The exported model
(hub/models/motionnet/pb_motionnet.onnx + .json) is trained on all subjects except a held-out calibration set
that tunes the unknown cutoff. It is exported unvalidated: the hub only displays its opinion until
ml/validate_real.py passes it on held-out team recordings.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pbml import train as T  # noqa: E402
from pbml.features_multimodal import CLASSES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "hub" / "models" / "motionnet"


def load_samples(args, rng) -> tuple:
    samples, sources = [], []
    if args.synthetic:
        from pbml.synth_skeleton import synthetic_people

        items = synthetic_people(n_subjects=args.synthetic, seed=args.seed)
        samples += T.samples_from_sequences(items, rng, n_aug=args.n_aug)
        sources.append(f"synthetic({args.synthetic} subjects) - code-path check only")
    if args.public:
        from pbml.datasets import PUBLIC_ROOT, intellirehab, rehab24, spar

        r24 = rehab24.load(exercises=(1, 2)) if (PUBLIC_ROOT / "rehab24" / "3d_joints").exists() else []
        ir = intellirehab.load() if any((PUBLIC_ROOT / "intellirehab").rglob("*.txt")) else []
        sp = spar.load() if (PUBLIC_ROOT / "SPAR" / "csv").exists() else []
        print(f"public: REHAB24-6 {len(r24)} reps, IntelliRehabDS {len(ir)} reps, SPAR {len(sp)} IMU segments")
        samples += T.samples_from_sequences(r24 + ir, rng, n_aug=args.n_aug)
        samples += T.samples_from_imu_segments(sp, rng, n_aug=args.n_aug)
        sources += [s for s, n in (("REHAB24-6", r24), ("IntelliRehabDS", ir), ("SPAR", sp)) if n]
    if args.real:
        from pbml.real import load_sessions

        seqs = load_sessions(args.real)
        print(f"real: {len(seqs)} recorded blocks from {len({s.subject for s in seqs})} volunteers")
        samples += T.samples_from_sequences(seqs, rng, n_aug=args.n_aug)
        sources.append(f"team recordings ({len({s.subject for s in seqs})} volunteers)")
    return samples, sources


def limitations(w: "T.Windows") -> list:
    """What this run cannot claim, written into the report and the model metadata."""
    out = []
    real = w.source == "real"
    if not real.any():
        out.append("Skeleton branch has never seen a RealSense + RTMPose skeleton (public Kinect / motion-capture "
                   "only). Results do not describe the Clinic Station until validated on team recordings.")
    if not (T.has_modality(w, "fused") & real).any():
        out.append("Camera + strap together was not measured on real people: no source records both. "
                   "Needs team recordings with the straps worn.")
    imu = T.has_modality(w, "imu")
    if (imu & (w.source == "imu")).any() and not (imu & real).any():          # "imu" = SPAR segments
        out.append("Strap branch trained only on a wrist-worn Apple Watch (SPAR). It does not transfer to "
                   "BNO085 straps on the arm, forearm and chest; the hub ignores strap input until validated.")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--synthetic", type=int, default=0, metavar="N", help="add N synthetic subjects")
    p.add_argument("--public", action="store_true", help="REHAB24-6 + IntelliRehabDS + SPAR (ml/fetch_public.py)")
    p.add_argument("--real", type=Path, default=None, help="guided recordings root (ml/data/real)")
    p.add_argument("--n-aug", type=int, default=2, help="augmented copies per skeleton sequence")
    p.add_argument("--epochs", type=int, default=25)
    p.add_argument("--folds", type=int, default=None, help="GroupKFold K instead of LOSO")
    p.add_argument("--no-cv", action="store_true")
    p.add_argument("--no-export", action="store_true")
    p.add_argument("--out", type=Path, default=MODEL_DIR)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    if not (args.synthetic or args.public or args.real):
        p.error("choose at least one of --synthetic N, --public, --real DIR")

    rng = np.random.default_rng(args.seed)
    t0 = time.time()
    samples, sources = load_samples(args, rng)
    w = T.make_windows(samples)
    counts = {c: int(n) for c, n in zip(CLASSES, np.bincount(w.exercise, minlength=len(CLASSES)))}
    print(f"{len(samples)} sequences -> {len(w)} windows, {len(set(w.groups))} subjects, "
          f"features {time.time() - t0:.0f} s\n  per class: {counts}")

    cv = {}
    if not args.no_cv:
        print("cross-validation (subject-grouped) ...")
        cv = T.grouped_cv(w, n_folds=args.folds, epochs=args.epochs, seed=args.seed, verbose=True)
        for mode in ("skeleton", "imu", "fused"):
            m = cv.get(mode)
            if m:
                extra = "".join(f"  {k} {m[k]:.3f}" for k in ("unknown_rejection", "known_false_reject",
                                                               "phase_frame_acc", "form_sensitivity",
                                                               "form_specificity") if k in m)
                print(f"  {mode:>8}: acc {m['accuracy']:.3f}  macro-F1 {m['macro_f1']:.3f}{extra}  (n={m['n']})")

    lim = limitations(w)
    for line in lim:
        print(f"  LIMITATION: {line}")
    if not args.no_export:
        model, thr, cal = T.fit_and_calibrate(w, np.arange(len(w)), epochs=args.epochs, seed=args.seed)
        # calibration_subjects must stay a list: validate_real.py excludes these volunteers from its test
        extra = {"calibration_subjects": cal["held_out"], "calibration_in_sample_modes": cal["in_sample_modes"],
                 "limitations": lim, "real_training_subjects": sorted(set(w.groups[w.source == "real"].tolist()))}
        path = T.export_onnx(model, args.out, thr, cv, sources, extra)
        tuned = f"tuned on held-out subjects {cal['held_out']}"
        if cal["in_sample_modes"]:
            tuned += f"; {', '.join(cal['in_sample_modes'])} tuned in-sample (too few subjects)"
        print(f"exported {path} (energy thresholds {', '.join(f'{k} {v:.2f}' for k, v in thr.items())}, "
              f"{tuned})\n  NOT validated on real recordings: the hub will only "
              f"display its opinion until ml/validate_real.py passes it.")
    if cv:
        rep = ROOT / "ml" / "reports" / f"motionnet_cv_{time.strftime('%Y%m%d-%H%M')}.json"
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(json.dumps({"sources": sources, "classes": list(CLASSES), "cv": cv, "limitations": lim},
                                  indent=1))
        print(f"report {rep}")


if __name__ == "__main__":
    main()
