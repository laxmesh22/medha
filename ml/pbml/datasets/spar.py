"""SPAR: Shoulder Physiotherapy Activity Recognition (Burns et al. 2018, Physiol Meas 39:075007).

https://github.com/dmbee/SPAR-dataset (GPL-3.0). 20 healthy subjects x 2 shoulders x 7 exercises x 20 reps,
one Apple Watch on the wrist, 6-axis IMU at 50 Hz (acc in g, gyro in rad/s). Files: ``csv/S{n}_E{e}_{L|R}.csv``.

Converted to the team ``Segment`` format: acc m/s^2, gyro deg/s, resampled to 100 Hz.
Only the per-file (20-rep) segment is labelled; there are no rep boundaries or correctness labels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from ..data import FS, G, Segment
from .common import PUBLIC_ROOT, download, resample

URL = "https://raw.githubusercontent.com/dmbee/SPAR-dataset/master/csv/{name}.csv"
FS_SPAR = 50.0
SUBJECTS = range(1, 21)
CODES = {0: "PEN", 1: "ABD", 2: "FEL", 3: "IR", 4: "ER", 5: "TRAP", 6: "ROW"}
TO_CLASS = {0: "pendulum", 1: "abduction", 2: "flexion", 3: "internal_rotation",
            4: "external_rotation", 5: "unknown", 6: "unknown"}
SIDES = {"R": "right", "L": "left"}


def file_names() -> list:
    return [f"S{s}_E{e}_{side}" for s in SUBJECTS for e in CODES for side in SIDES]


def fetch(root: Path = PUBLIC_ROOT / "SPAR") -> Path:
    for name in file_names():
        download(URL.format(name=name), Path(root) / "csv" / f"{name}.csv")
    return Path(root)


def parse_name(stem: str) -> tuple:
    s, e, side = stem.split("_")
    return int(s[1:]), int(e[1:]), SIDES[side]


def load_file(path: Path) -> Segment:
    path = Path(path)
    s, e, side = parse_name(path.stem)
    a = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    a = resample(a[np.all(np.isfinite(a), axis=1)], FS_SPAR, FS)
    return Segment(subject=f"SPAR{s:02d}", exercise=TO_CLASS[e], acc=a[:, :3] * G,
                   gyro=np.degrees(a[:, 3:6]), name=f"{path.stem}_{CODES[e]}", side=side)


def load(root: Path = PUBLIC_ROOT / "SPAR", subjects: Optional[set] = None) -> list:
    segs = []
    for f in sorted((Path(root) / "csv").glob("S*_E*_*.csv")):
        if subjects is not None and parse_name(f.stem)[0] not in subjects:
            continue
        segs.append(load_file(f))
    return segs
