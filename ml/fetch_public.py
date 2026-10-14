"""Download the public datasets into ml/data/public/ (git-ignored).

    hub/.venv/Scripts/python.exe ml/fetch_public.py                 # all three
    hub/.venv/Scripts/python.exe ml/fetch_public.py --only spar rehab24
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pbml.datasets import intellirehab, rehab24, spar  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=["spar", "intellirehab", "rehab24"],
                    default=["spar", "intellirehab", "rehab24"])
    ap.add_argument("--rehab24-exercises", type=int, nargs="+", default=[1, 2],
                    help="REHAB24-6 exercise ids to fetch (1 = arm abduction, 2 = arm VW; 3-6 are not shoulder)")
    args = ap.parse_args()
    if "spar" in args.only:
        print("SPAR ->", spar.fetch())
    if "rehab24" in args.only:
        print("REHAB24-6 ->", rehab24.fetch(exercises=tuple(args.rehab24_exercises)))
    if "intellirehab" in args.only:
        print("IntelliRehabDS ->", intellirehab.fetch())


if __name__ == "__main__":
    main()
