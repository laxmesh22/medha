"""Lee 2024 baseline on REAL data: SPAR wrist-IMU shoulder exercises (20 people, both arms).

    hub/.venv/Scripts/python.exe ml/run_spar_baseline.py [--chunks 4] [--out ml/reports/spar_lee2024.json]

Each SPAR file is 20 reps of one exercise; it is split into `chunks` segments (~5 reps) so every person
contributes several samples per class. Reports the paper's random 80:20 split and leave-one-subject-out.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from pbml.datasets import spar  # noqa: E402
from pbml.lee2024 import evaluate_loso, evaluate_random_split  # noqa: E402


def chunked(segs, chunks):
    out = []
    for s in segs:
        for k, idx in enumerate(np.array_split(np.arange(len(s.acc)), chunks)):
            if len(idx) >= 100:  # >= 1 s at 100 Hz
                out.append(replace(s, acc=s.acc[idx], gyro=s.gyro[idx], name=f"{s.name}_c{k}"))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--chunks", type=int, default=4, help="segments per 20-rep file (~5 reps each)")
    p.add_argument("--out", type=Path, default=Path(__file__).parent / "reports" / "spar_lee2024.json")
    args = p.parse_args()

    segs = chunked(spar.load(), args.chunks)
    if not segs:
        sys.exit("No SPAR data: run  hub/.venv/Scripts/python.exe ml/fetch_public.py --only spar")
    print(f"SPAR: {len(segs)} segments, {len({s.subject for s in segs})} people, "
          f"{len({s.exercise for s in segs})} classes (both arms)")
    reports = [evaluate_random_split(segs), evaluate_loso(segs)]
    for r in reports:
        print(f"\n{r.protocol:>14}: accuracy {r.accuracy:.3f}   macro-F1 {r.macro_f1:.3f}")
        if r.per_fold:
            print(f"{'':>14}  per-person accuracy {min(r.per_fold):.3f} - {max(r.per_fold):.3f}")
        for a, b, rate in r.top_confusions(4):
            print(f"{'':>14}  {a} -> {b}: {rate:.1%}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"dataset": "SPAR (Burns et al. 2018)", "chunks": args.chunks,
                                    "reports": [r.to_dict() for r in reports]}, indent=2))
    print(f"\nreport: {args.out}")


if __name__ == "__main__":
    main()
