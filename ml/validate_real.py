"""Gate PB-MotionNet on held-out Physio Buddy recordings before the hub lets it veto anything.

    hub/.venv/Scripts/python.exe ml/validate_real.py --real ml/data/real [--model hub/models/motionnet]

Replays every recorded block through the hub's own ``MotionNetRunner`` (same features, window, thresholds),
then applies the coach's hybrid rules to each rep the rules counted. The outcome is written into
pb_motionnet.json under "real_validation"; the hub enables network vetoes, network issues and auto-detect only
when it passed for this exact model_version. Volunteers the model was trained or calibrated on are excluded.
The strap branch stays disabled (imu_passed false) until recordings include strap data.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from physiobuddy_hub.core.coach import EXERCISES, NN_FLAG_RULES, NN_MIN_FRAMES, NN_UNKNOWN_MAJORITY  # noqa: E402
from physiobuddy_hub.core.skeleton_kin import SkeletonKinematics  # noqa: E402
from physiobuddy_hub.ml.motionnet_infer import DEFAULT_DIR, MotionNetRunner  # noqa: E402
from physiobuddy_hub.recorder import ATTEMPT_INDEX  # noqa: E402
from pbml.datasets.common import to_skeleton3d  # noqa: E402
from pbml.real import _runs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COUNTED = ATTEMPT_INDEX["counted"]


def replay(runner: MotionNetRunner, z) -> list:
    """Per-frame runner output (None until the buffer fills) for one recorded block."""
    side, up = str(z["side"]), z["up_cam"].astype(float)
    base = float(z["shrug_baseline"])
    base = None if np.isnan(base) else base
    kin = SkeletonKinematics(side)
    kin.set_shrug_baseline(base)
    runner.reset()
    outs = []
    for p in z["points"].astype(float):
        sk = to_skeleton3d(p)
        outs.append(runner.push(sk, kin.compute(sk, up).to_dict(), side, up, base))
    return outs


def judge_rep(outs: list, exercise: str) -> dict:
    """The coach's hybrid decision for one counted rep (see Coach._finish_rep)."""
    outs = [o for o in outs if o is not None]
    if len(outs) < NN_MIN_FRAMES:
        return {"judged": False}
    unknown = np.mean([o["is_unknown"] for o in outs])
    active = any(o["phase"] in ("raising", "hold") for o in outs)
    thr = outs[-1].get("comp_threshold", 0.7)
    watch = EXERCISES[exercise].watch_flags
    flags = sorted(f for f in NN_FLAG_RULES
                   if max(o["comp_probs"].get(f, 0.0) for o in outs) >= thr
                   and (f == "TOO_FAST" or any(r in watch for r in NN_FLAG_RULES[f])))
    pred = max(set(o["predicted_exercise"] for o in outs), key=[o["predicted_exercise"] for o in outs].count)
    return {"judged": True, "vetoed": bool(unknown > NN_UNKNOWN_MAJORITY or not active), "flags": flags,
            "agrees": pred == exercise}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--real", type=Path, required=True, help="guided recordings root (ml/data/real)")
    p.add_argument("--model", type=Path, default=DEFAULT_DIR)
    p.add_argument("--min-subjects", type=int, default=3)
    p.add_argument("--min-reps", type=int, default=30, help="counted correct reps needed to judge")
    p.add_argument("--max-veto", type=float, default=0.05, help="max share of correct reps the network rejects")
    p.add_argument("--max-flag", type=float, default=0.10, help="max share of correct reps given network issues")
    p.add_argument("--dry-run", action="store_true", help="report only, do not write the model metadata")
    p.add_argument("--report-dir", type=Path, default=ROOT / "ml" / "reports")
    args = p.parse_args()

    meta_path = args.model / "pb_motionnet.json"
    meta = json.loads(meta_path.read_text())
    runner = MotionNetRunner.from_dir(args.model)
    if runner.predict_fn is None:
        sys.exit(f"no loadable model in {args.model}")
    seen = set(meta.get("real_training_subjects", [])) | set(meta.get("calibration_subjects", []))

    correct, mistakes, unknown_frames, subjects, skipped = [], [], [], set(), []
    for f in sorted(args.real.glob("*/*/*.npz")):
        z = np.load(f, allow_pickle=False)
        subj, ex = str(z["subject"]), str(z["exercise"])
        if subj in seen:
            skipped.append(f"{f.parent.parent.name}/{f.parent.name}/{f.name}: subject used in training")
            continue
        if ex != "unknown" and "attempt" not in z.files:
            skipped.append(f"{f.name}: no per-attempt labels")
            continue
        outs = replay(runner, z)
        subjects.add(subj)
        if ex == "unknown":
            if str(f.stem).endswith("unknown"):
                unknown_frames += [o["is_unknown"] for o in outs if o is not None]
            continue
        for a, b in _runs(z["attempt"] == COUNTED):
            r = judge_rep(outs[a:b], ex)
            if not r["judged"]:
                continue
            r.update(subject=subj, block=f.stem, comp=str(z["comp"]))
            (correct if int(z["correct"]) == 1 else mistakes).append(r)

    def share(rows, key):
        return round(float(np.mean([bool(r[key]) for r in rows])), 4) if rows else None

    res = {
        "model_version": meta.get("model_version"),
        "subjects": sorted(subjects), "n_subjects": len(subjects),
        "correct_reps": len(correct), "mistake_reps": len(mistakes),
        "correct_rep_veto_rate": share(correct, "vetoed"),
        "correct_rep_nn_issue_rate": share(correct, "flags"),
        "correct_rep_exercise_agreement": share(correct, "agrees"),
        "mistake_rep_scripted_flag_found": round(float(np.mean([r["comp"] in r["flags"] for r in mistakes
                                                                if r["comp"]])), 4)
        if any(r["comp"] for r in mistakes) else None,
        "everyday_movement_rejected": round(float(np.mean(unknown_frames)), 4) if unknown_frames else None,
        "criteria": {"min_subjects": args.min_subjects, "min_reps": args.min_reps,
                     "max_veto": args.max_veto, "max_flag": args.max_flag},
        "skipped": skipped,
    }
    fails = []
    if res["n_subjects"] < args.min_subjects:
        fails.append(f"{res['n_subjects']} held-out volunteers < {args.min_subjects}")
    if res["correct_reps"] < args.min_reps:
        fails.append(f"{res['correct_reps']} counted correct reps < {args.min_reps}")
    if res["correct_rep_veto_rate"] is not None and res["correct_rep_veto_rate"] > args.max_veto:
        fails.append(f"rejects {res['correct_rep_veto_rate']:.1%} of correct reps > {args.max_veto:.0%}")
    if res["correct_rep_nn_issue_rate"] is not None and res["correct_rep_nn_issue_rate"] > args.max_flag:
        fails.append(f"adds issues to {res['correct_rep_nn_issue_rate']:.1%} of correct reps > {args.max_flag:.0%}")
    res["passed"] = not fails
    res["failures"] = fails
    res["imu_passed"] = False
    res["imu_reason"] = "recordings contain no strap data yet"
    res["date"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    rep = args.report_dir / f"real_validation_{time.strftime('%Y%m%d-%H%M')}.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "skipped"}, indent=1))
    print(f"report {rep}")
    if not args.dry_run:
        meta["real_validation"] = res
        meta_path.write_text(json.dumps(meta, indent=1))
        print(("PASSED: the hub will use network vetoes for " if res["passed"] else
               "NOT passed: the hub keeps the network advisory for ") + str(meta.get("model_version")))


if __name__ == "__main__":
    main()
