"""IntelliRehabDS (Miron et al. 2021, Data 6(5):46). https://zenodo.org/records/4610859 (CC BY 4.0).

29 subjects (15 patients, 14 healthy), Kinect v2 skeletons (25 joints, metres, ~30 Hz), one file per repetition:
``SubjectID_DateID_GestureLabel_RepNo_CorrectLabel_Position.txt``. CorrectLabel 1 = correct, 2 = incorrect.
Raw lines (as parsed by the authors' loader github.com/alina-miron/intellirehabds dataio/SkeletonUtils.py):
``frame, body_index, timestamp, (JointName, TrackedStatus, x, y, z, u, v) x 25``.

Kinect camera space is X to the sensor's left, Y up, Z forward; RealSense is X right, Y down, Z forward,
so x_rs = -x_k, y_rs = -y_k, z_rs = z_k (a proper rotation). Kinect joint sides are anatomical, like COCO.
Ears/eyes do not exist in Kinect: left NaN (shrug unavailable), Head is used as nose.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Optional

import numpy as np

from .common import PUBLIC_ROOT, SkeletonSequence, download

URL = "https://zenodo.org/records/4610859/files/SkeletonData.zip?download=1"
FPS = 30.0
KINECT_TO_RS = np.diag([-1.0, -1.0, 1.0])

# Table 1 of the paper (gesture index, name) -> class + *anatomical* moving side for the hub kinematics.
# The gesture names' Left/Right are the opposite anatomical arm: checked on the data (14 Oct 2026), gesture 2
# "Shoulder Flexion Left" raises the joints Kinect labels ShoulderRight/ElbowRight to ~160 deg while the
# Left ones stay < 30 deg (and vice versa for 3, 4, 5), with the thorax anterior axis pointing at the camera.
GESTURES = {
    0: ("elbow_flexion_left", "unknown", "right"),
    1: ("elbow_flexion_right", "unknown", "left"),
    2: ("shoulder_flexion_left", "flexion", "right"),
    3: ("shoulder_flexion_right", "flexion", "left"),
    4: ("shoulder_abduction_left", "abduction", "right"),
    5: ("shoulder_abduction_right", "abduction", "left"),
    6: ("shoulder_forward_elevation", "flexion", "right"),  # both arms, hands clasped
    7: ("side_tap_left", "unknown", "right"),
    8: ("side_tap_right", "unknown", "left"),
}

# COCO-17 index <- Kinect v2 joint name
COCO_FROM_KINECT = {
    0: "Head", 5: "ShoulderLeft", 6: "ShoulderRight", 7: "ElbowLeft", 8: "ElbowRight",
    9: "WristLeft", 10: "WristRight", 11: "HipLeft", 12: "HipRight", 13: "KneeLeft", 14: "KneeRight",
    15: "AnkleLeft", 16: "AnkleRight",
}

NAME_RE = re.compile(r"^(?P<subject>[^_]+)_(?P<date>[^_]+)_(?P<gesture>\d)_(?P<rep>\d+)_(?P<correct>\d)_(?P<pos>.+)$")


def fetch(root: Path = PUBLIC_ROOT / "intellirehab") -> Path:
    root = Path(root)
    z = download(URL, root / "SkeletonData.zip")
    if not any(root.rglob("*.txt")) or not list(_raw_files(root)):
        with zipfile.ZipFile(z) as zf:
            zf.extractall(root)
    return root


def _raw_files(root: Path):
    files = sorted(Path(root).rglob("*.txt"))
    raw = [f for f in files if "simplified" not in str(f).lower() and NAME_RE.match(f.stem)]
    return raw


def parse_lines(lines) -> np.ndarray:
    """Raw lines -> (T, 17, 3) RealSense-frame points of the most frequent body."""
    rows = []
    for line in lines:
        line = line.strip()
        if not line or "Version" in line:
            continue
        w = [x.strip() for x in line.split(",")]
        if len(w) != 3 + 25 * 7:
            continue
        rows.append(w)
    if not rows:
        return np.empty((0, 17, 3))
    body = Counter(r[1] for r in rows).most_common(1)[0][0]
    out = []
    for w in rows:
        if w[1] != body:
            continue
        joints = {}
        for j in range(25):
            name = w[3 + j * 7].strip("(")
            tracked = w[3 + j * 7 + 1]
            xyz = np.array([float(w[3 + j * 7 + k]) for k in (2, 3, 4)])
            ok = tracked != "NotTracked" and np.any(xyz != 0)
            joints[name] = KINECT_TO_RS @ xyz if ok else np.full(3, np.nan)
        pts = np.full((17, 3), np.nan)
        for coco, kname in COCO_FROM_KINECT.items():
            if kname in joints:
                pts[coco] = joints[kname]
        out.append(pts)
    return np.asarray(out)


def load_file(path: Path) -> Optional[SkeletonSequence]:
    path = Path(path)
    m = NAME_RE.match(path.stem)
    if m is None:
        return None
    gesture = int(m["gesture"])
    correct = {"1": True, "2": False}.get(m["correct"])  # 3 = not labelled
    gname, cls, side = GESTURES[gesture]
    with open(path, encoding="utf-8", errors="ignore") as fh:
        pts = parse_lines(fh)
    if len(pts) == 0:
        return None
    return SkeletonSequence(subject=f"IR{m['subject']}", exercise=cls, side=side, points=pts, fps=FPS,
                            source="intellirehab", name=path.stem, correct=correct,
                            meta={"gesture": gname, "position": m["pos"], "date": m["date"],
                                  "rep": int(m["rep"])})


def load(root: Path = PUBLIC_ROOT / "intellirehab", positions: Optional[set] = None) -> list:
    seqs = []
    for f in _raw_files(root):
        s = load_file(f)
        if s is not None and (positions is None or s.meta["position"].lower() in positions):
            seqs.append(s)
    return seqs
