"""One table for the pitch: rules vs Lee 2024 MLP vs Sassi-style random forest vs PB-MotionNet.

    hub/.venv/Scripts/python.exe ml/run_benchmark.py --synthetic 6 --epochs 6       # code-path check only
    hub/.venv/Scripts/python.exe ml/run_benchmark.py --public --folds 5
    hub/.venv/Scripts/python.exe ml/run_benchmark.py --public --real ml/data/real

All window-level methods use the same subject-grouped splits (LOSO, or GroupKFold with --folds). Lee 2024 is
segment-level as published, reported under its own random 80:20 protocol *and* LOSO.
Writes ml/reports/benchmark_<time>.json and .md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pbml import train as T  # noqa: E402
from pbml.data import FS, Segment  # noqa: E402
from pbml.datasets.common import resample  # noqa: E402
from pbml.features_multimodal import CLASSES, D_IMU, D_POS, D_SKEL  # noqa: E402
from pbml.lee2024 import evaluate_loso, evaluate_random_split  # noqa: E402
from train_motionnet import limitations, load_samples  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = CLASSES.index("unknown")


# ------------------------------------------------------------------------------- rules only
def rules_predict(x: np.ndarray) -> tuple:
    """Geometry-only exercise + form decision per window, from the same kinematic channels the coach uses."""
    kin = x[:, :, D_POS:D_SKEL]
    elev, plane = kin[..., 0] * 180, np.degrees(np.arctan2(kin[..., 2], kin[..., 3]))
    rot, sag, lat, shrug = kin[..., 5] * 90, kin[..., 6] * 45, kin[..., 7] * 45, kin[..., 8]
    ex = np.full(len(x), UNKNOWN)
    for i in range(len(x)):
        moving = elev[i] > 30
        if moving.sum() >= 5:
            p = float(np.median(plane[i][moving]))
            if -30 <= p < 30:
                ex[i] = CLASSES.index("flexion")
            elif 60 <= p <= 120:
                ex[i] = CLASSES.index("abduction")
        elif (np.abs(rot[i]) > 0).sum() >= 5 and np.abs(rot[i]).max() > 20:
            ex[i] = CLASSES.index("external_rotation" if rot[i][np.abs(rot[i]).argmax()] > 0 else "internal_rotation")
    fix = (np.abs(sag) > 10).any(1) | (np.abs(lat) > 10).any(1) | (shrug < -0.12).any(1)
    return ex, fix


def form_scores(fix_pred: np.ndarray, correct: np.ndarray) -> dict:
    lab = correct >= 0
    if not lab.any() or len(set(correct[lab])) < 2:
        return {}
    t = correct[lab] == 0
    p = fix_pred[lab]
    return {"form_sensitivity": round(float(p[t].mean()), 4), "form_specificity": round(float((~p[~t]).mean()), 4)}


# ------------------------------------------------------------------------- Sassi-style RF
def summary_features(x: np.ndarray, mode: str) -> np.ndarray:
    ch = x[:, :, D_POS:D_SKEL] if mode == "skeleton" else x[:, :, D_SKEL:D_SKEL + D_IMU]
    return np.concatenate([ch.mean(1), ch.std(1), ch.min(1), ch.max(1)], axis=1)


def rf_cv(w, splitter, mode: str) -> dict:
    sel = T.has_modality(w, mode)
    if not sel.any():
        return None
    ws = w.subset(np.flatnonzero(sel))
    X = summary_features(ws.x, mode)
    yt, yp = [], []
    for tr, te in splitter.split(X, ws.exercise, ws.groups):
        rf = RandomForestClassifier(n_estimators=200, min_samples_leaf=2, n_jobs=-1, random_state=0)
        rf.fit(X[tr], ws.exercise[tr])
        te = te[~ws.aug[te]]                          # score real windows only, never augmented copies
        yt.append(ws.exercise[te]); yp.append(rf.predict(X[te]))
    return T.metrics(np.concatenate(yt), np.concatenate(yp), ws)


# ------------------------------------------------------------------------------------ Lee
def imu_segments(samples) -> list:
    """Window-free IMU segments for Lee 2024 (it classifies whole exercise segments at 100 Hz)."""
    segs = []
    for s in samples:
        if s.x[0, -1] <= 0 or s.source.endswith("~aug") or "~aug" in s.name:
            continue
        a = s.x[:, D_SKEL:D_SKEL + 6]
        a = resample(a, 30.0, FS)
        segs.append(Segment(subject=s.subject, exercise=CLASSES[s.exercise], acc=a[:, :3] * 9.81,
                            gyro=a[:, 3:] * 180.0, name=s.name))
    return segs


def fmt_row(name: str, m: dict) -> str:
    if not m:
        return f"| {name} | n/a | n/a | n/a | n/a | n/a |"
    g = lambda k: f"{m[k]:.3f}" if k in m else "-"  # noqa: E731
    return (f"| {name} | {g('accuracy')} | {g('macro_f1')} | {g('unknown_rejection')} | "
            f"{g('form_sensitivity')} / {g('form_specificity')} | {m.get('n', '-')} |")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--synthetic", type=int, default=0, metavar="N")
    p.add_argument("--public", action="store_true")
    p.add_argument("--real", type=Path, default=None)
    p.add_argument("--n-aug", type=int, default=2)
    p.add_argument("--epochs", type=int, default=25)
    p.add_argument("--folds", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    if not (args.synthetic or args.public or args.real):
        p.error("choose at least one of --synthetic N, --public, --real DIR")

    rng = np.random.default_rng(args.seed)
    samples, sources = load_samples(args, rng)
    w = T.make_windows(samples)
    splitter = LeaveOneGroupOut() if args.folds is None else GroupKFold(n_splits=min(args.folds, len(set(w.groups))))
    protocol = "LOSO" if args.folds is None else f"GroupKFold({args.folds}) by subject"
    print(f"{len(w)} windows, {len(set(w.groups))} subjects, protocol {protocol}")
    res = {"sources": sources, "protocol": protocol, "synthetic": bool(args.synthetic) and not args.public
           and not args.real, "rows": {}}

    sk = T.has_modality(w, "skeleton") & ~w.aug
    if sk.any():
        ws = w.subset(np.flatnonzero(sk))
        ex, fix = rules_predict(ws.x)
        res["rows"]["Rules only (geometry + thresholds)"] = {**T.metrics(ws.exercise, ex, ws), **form_scores(fix, ws.correct)}

    segs = imu_segments([s for s in samples if "~aug" not in s.name])
    if len({s.subject for s in segs}) >= 2 and len({s.exercise for s in segs}) >= 2:
        r1, r2 = evaluate_random_split(segs), evaluate_loso(segs)
        res["rows"]["Lee 2024 MLP, IMU, random 80:20"] = {"accuracy": round(r1.accuracy, 4), "macro_f1": round(r1.macro_f1, 4), "n": len(segs)}
        res["rows"]["Lee 2024 MLP, IMU, LOSO"] = {"accuracy": round(r2.accuracy, 4), "macro_f1": round(r2.macro_f1, 4), "n": len(segs)}

    for mode in ("skeleton", "imu"):
        m = rf_cv(w, splitter, mode)
        if m:
            res["rows"][f"Random forest (Sassi-style), {mode}"] = m

    cv = T.grouped_cv(w, n_folds=args.folds, epochs=args.epochs, seed=args.seed)
    for mode in ("skeleton", "imu", "fused"):
        res["rows"][f"PB-MotionNet, {mode}"] = cv.get(mode)

    stamp = time.strftime("%Y%m%d-%H%M")
    out = ROOT / "ml" / "reports" / f"benchmark_{stamp}"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Movement-judging benchmark ({stamp})", "",
             f"Sources: {', '.join(sources)}. Protocol: {protocol} (window {T.WINDOW} frames).", ""]
    if res["synthetic"]:
        lines += ["**Synthetic data: these numbers only check the code path.**", ""]
    lines += ["| Method | Accuracy | Macro-F1 | Unknown rejected | Form sens / spec | n |",
              "|---|---|---|---|---|---|"]
    lines += [fmt_row(k, v) for k, v in res["rows"].items()]
    lines += ["", "Scored on original windows of held-out subjects only (augmented copies are training data). "
              "PB-MotionNet's unknown cutoff is tuned on held-out calibration subjects.",
              "Angles in degrees always come from geometry (SkeletonKinematics); no method here outputs degrees."]
    res["limitations"] = limitations(w)
    if res["limitations"]:
        lines += ["", "## Limitations", ""] + [f"- {x}" for x in res["limitations"]]
    out.with_suffix(".json").write_text(json.dumps(res, indent=1))
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten {out}.json / .md")


if __name__ == "__main__":
    main()
