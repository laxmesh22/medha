"""Run the Lee 2024 baseline under both protocols.

    python ml/run_baseline.py --synthetic                 # code-path check on simulated data
    python ml/run_baseline.py --data path/to/dataset      # real recordings (format: pbml/data.py)
    python ml/run_baseline.py --synthetic --showcase      # only our frozen-shoulder subset of classes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pbml.data import load_dataset, synthetic_dataset  # noqa: E402
from pbml.exercises import CLASS_IDS, SHOWCASE_IDS  # noqa: E402
from pbml.lee2024 import evaluate_loso, evaluate_random_split  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", type=Path)
    src.add_argument("--synthetic", action="store_true")
    p.add_argument("--subjects", type=int, default=10)
    p.add_argument("--showcase", action="store_true", help="restrict to SHOWCASE_IDS")
    p.add_argument("--out", type=Path, default=None, help="write JSON report here")
    args = p.parse_args()

    if args.synthetic:
        segs = synthetic_dataset(n_subjects=args.subjects,
                                 exercises=SHOWCASE_IDS if args.showcase else CLASS_IDS)
    else:
        segs = load_dataset(args.data)
        if args.showcase:
            segs = [s for s in segs if s.exercise in SHOWCASE_IDS]
    subjects = sorted({s.subject for s in segs})
    print(f"{len(segs)} segments, {len(subjects)} subjects, {len({s.exercise for s in segs})} classes"
          + ("  [SYNTHETIC - numbers only check the code path]" if args.synthetic else ""))

    reports = [evaluate_random_split(segs), evaluate_loso(segs)]
    for r in reports:
        print(f"\n{r.protocol:>14}: accuracy {r.accuracy:.3f}   macro-F1 {r.macro_f1:.3f}")
        if r.per_fold:
            print(f"{'':>14}  per-subject accuracy range {min(r.per_fold):.3f} - {max(r.per_fold):.3f}")
        for a, b, rate in r.top_confusions(3):
            print(f"{'':>14}  {a} -> {b}: {rate:.1%}")
    print("\nLee 2024 reported 0.925 on a random 80:20 split (58 patients, real data).")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"synthetic": args.synthetic, "reports": [r.to_dict() for r in reports]}, indent=2))
        print(f"report written to {args.out}")


if __name__ == "__main__":
    main()
