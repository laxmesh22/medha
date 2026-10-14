"""REHAB24-6 (Cernek, Sedmidubsky, Budikova, SISAP 2024). https://zenodo.org/records/13305826
Licence: academic / non-profit non-commercial research only.

10 subjects, OptiTrack skeleton (26 joints), 30 FPS, 1,072 segmented reps with physiotherapist-instructed
correctness (``Segmentation.csv``: first/last frame index the 30 FPS files). ``3d_joints.zip`` holds
``Ex{k}/PM_xxx-30fps.npy`` arrays of shape (T, 26, 4) = x, y (up), z in metres + homogeneous 1.
Only the 30 FPS members are fetched (~112 MB of the 551 MB zip) using HTTP range requests.

Ex1 = right-arm abduction -> ``abduction``. Ex2-6 (arm VW, push-ups, leg abduction, lunge, squat) -> ``unknown``.
World coordinates are converted to a virtual D455 in front of the subject (``world_to_virtual_camera``).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

import numpy as np

from .common import PUBLIC_ROOT, RemoteZip, SkeletonSequence, download, world_to_virtual_camera

RECORD = "https://zenodo.org/api/records/13305826/files/{name}/content"
JOINTS_ZIP_SIZE = 551298977
FPS = 30.0
UP_WORLD = np.array([0.0, 1.0, 0.0])
EXERCISE_CLASS = {1: "abduction", 2: "unknown", 3: "unknown", 4: "unknown", 5: "unknown", 6: "unknown"}

# COCO-17 index <- OptiTrack joint index (joints_names.txt). "Arm" = humeral head, "ForeArm" = elbow,
# "Hand" = wrist, "UpLeg" = hip, "Leg" = knee, "Foot" = ankle. Head stands in for the nose; no ears.
COCO_FROM_MOCAP = {0: 4, 5: 7, 6: 12, 7: 8, 8: 13, 9: 9, 10: 14, 11: 16, 12: 21, 13: 17, 14: 22, 15: 18, 16: 23}


def fetch(root: Path = PUBLIC_ROOT / "rehab24", exercises=(1, 2)) -> Path:
    root = Path(root)
    for name in ("Segmentation.csv", "Segmentation.txt", "joints_names.txt"):
        download(RECORD.format(name=name), root / name)
    want = [f"Ex{e}/" for e in exercises]
    rz = RemoteZip(RECORD.format(name="3d_joints.zip"), JOINTS_ZIP_SIZE)
    for name in sorted(rz.entries):
        if name.endswith("-30fps.npy") and any(name.startswith(w) for w in want):
            dest = root / "3d_joints" / name
            if dest.exists() and dest.stat().st_size > 0:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            np.save(dest, np.load(io.BytesIO(rz.read(name))))
    return root


def mocap_to_coco(frames: np.ndarray) -> np.ndarray:
    """(T, 26, 3|4) mocap world -> (T, 17, 3) COCO order, still in world coordinates."""
    out = np.full((len(frames), 17, 3), np.nan)
    for coco, j in COCO_FROM_MOCAP.items():
        out[:, coco] = frames[:, j, :3]
    return out


def read_segmentation(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def load(root: Path = PUBLIC_ROOT / "rehab24", exercises=(1, 2), distance_m: float = 2.3,
         yaw_deg: float = 0.0, skip_mocap_errors: bool = True) -> list:
    """One ``SkeletonSequence`` per segmented repetition (camera frame of a virtual front-facing D455)."""
    root = Path(root)
    rows = read_segmentation(root / "Segmentation.csv")
    cache: dict = {}
    seqs = []
    for r in rows:
        ex = int(r["exercise_id"])
        if ex not in exercises or (skip_mocap_errors and r["mocap_erroneous"] == "1"):
            continue
        f = root / "3d_joints" / f"Ex{ex}" / f"{r['video_id']}-30fps.npy"
        if not f.exists():
            continue
        if f not in cache:
            world = mocap_to_coco(np.load(f))
            cache[f] = world_to_virtual_camera(world, UP_WORLD, distance_m, yaw_deg)
        a, b = int(r["first_frame"]), int(r["last_frame"])
        pts = cache[f][a:b + 1]
        if len(pts) < 10:
            continue
        side = "left" if "left" in (r.get("exercise_subtype") or "") else "right"
        seqs.append(SkeletonSequence(
            subject=f"R24P{int(r['person_id']):02d}", exercise=EXERCISE_CLASS[ex], side=side, points=pts,
            fps=FPS, source="rehab24", name=f"{r['video_id']}_rep{r['repetition_number']}",
            correct=r["correctness"] == "1",
            meta={"exercise_id": ex, "video_id": r["video_id"], "first_frame": a, "last_frame": b,
                  "orientation": r["cam17_orientation"], "subtype": r.get("exercise_subtype")}))
    return seqs


def load_video(path: Path, distance_m: float = 2.3, yaw_deg: float = 0.0) -> Optional[np.ndarray]:
    """Whole recording (incl. pauses between reps) in the virtual camera frame, for unknown/rest windows."""
    return world_to_virtual_camera(mocap_to_coco(np.load(path)), UP_WORLD, distance_m, yaw_deg)
