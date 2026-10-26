"""PB-MotionNet inputs for training. The per-frame definition lives in the hub
(``physiobuddy_hub.ml.features``) so live inference and training can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from physiobuddy_hub.core.skeleton_kin import SkeletonKinematics
from physiobuddy_hub.ml.features import (  # noqa: F401  (re-exported)
    CLASSES, COMP_FLAGS, D_IMU, D_IN, D_KIN, D_MASK, D_POS, D_SKEL, FEATURE_VERSION, FPS, IMU_SENSORS, PHASES,
    STRIDE, WINDOW, frame_vector, imu_features, phase_labels, skeleton_features, windows,
)

from .datasets.common import DEFAULT_UP_CAM, SkeletonSequence, resample, to_skeleton3d

# Metric used for phase labels per class (matches the coach's ExerciseDef.metric).
PHASE_METRIC = {"flexion": "elevation", "abduction": "elevation", "external_rotation": "rotation",
                "internal_rotation": "rotation", "pendulum": "elevation", "unknown": "elevation"}


@dataclass
class Sample:
    """One labelled sequence ready for windowing."""
    x: np.ndarray                    # (T, D_IN)
    exercise: int                    # CLASSES index
    phase: np.ndarray                # (T,) PHASES index, -1 = no label
    correct: int = -1                # 1 correct, 0 needs fixing, -1 unknown
    comp: np.ndarray = field(default_factory=lambda: np.full(len(COMP_FLAGS), -1, np.int64))  # -1 = unknown
    subject: str = ""
    source: str = ""
    name: str = ""


def skeleton_sequence_features(points: np.ndarray, side: str, up_cam: np.ndarray = DEFAULT_UP_CAM,
                               shrug_baseline: Optional[float] = None) -> tuple:
    """(T, 17, 3) camera-frame points -> (features (T, D_IN), list of angle dicts)."""
    kin = SkeletonKinematics(side)
    kin.set_shrug_baseline(shrug_baseline)
    xs, angs = [], []
    for p in points:
        sk = to_skeleton3d(p)
        a = kin.compute(sk, up_cam).to_dict()
        f, ok = skeleton_features(sk, a, side, up_cam, shrug_baseline)
        xs.append(frame_vector(f, ok, None, False))
        angs.append(a)
    return np.asarray(xs, dtype=np.float32), angs


def angle_series(angs: list, key: str) -> np.ndarray:
    return np.array([np.nan if (a.get(key) or {}).get("value") is None else a[key]["value"] for a in angs])


def flag_fraction(angs: list, flag: str) -> float:
    return float(np.mean([flag in (a.get("flags") or []) for a in angs])) if angs else 0.0


def from_skeleton_sequence(seq: SkeletonSequence, shrug_baseline: Optional[float] = None,
                           straps: Optional[list] = None) -> Sample:
    """Skeleton sequence (optionally with paired strap frames, one ``imu_features`` dict per skeleton frame, from
    ``straps.strap_frames`` or a recording) -> Sample.

    Ground-truth ``meta["phase"]`` / ``meta["comp"]`` (synthetic data, recorder sessions) win over the weak
    phase labels derived from the angle trajectory.
    """
    pts = seq.points
    idx = np.arange(len(pts))
    if abs(seq.fps - FPS) > 0.5:
        idx = np.round(np.arange(0, len(pts), seq.fps / FPS)).astype(int)
        idx = idx[idx < len(pts)]
        pts = pts[idx]
    if shrug_baseline is None:
        shrug_baseline = seq.meta.get("shrug_baseline")
    x, angs = skeleton_sequence_features(pts, seq.side, seq.up_cam, shrug_baseline)
    if straps is not None:
        for t, i in enumerate(idx):
            f, ok = imu_features(straps[i])
            x[t, D_SKEL:D_SKEL + D_IMU] = f
            x[t, -1] = float(ok)
    if "phase" in seq.meta:
        phase = np.asarray(seq.meta["phase"], np.int64)[idx]
    elif seq.exercise != "unknown":
        phase = phase_labels(angle_series(angs, PHASE_METRIC[seq.exercise]))
    else:
        phase = np.full(len(x), -1, np.int64)
    comp = np.asarray(seq.meta["comp"], np.int64) if "comp" in seq.meta else np.full(len(COMP_FLAGS), -1, np.int64)
    correct = -1 if seq.correct is None else int(seq.correct)
    return Sample(x=x, exercise=CLASSES.index(seq.exercise), phase=phase, correct=correct, comp=comp,
                  subject=seq.subject, source=seq.source, name=seq.name)


def from_imu_segment(seg, sensor: str = "forearm") -> Sample:
    """Team/SPAR ``Segment`` (100 Hz, m/s^2, deg/s) -> strap-only Sample at 30 Hz.

    A wrist-worn IMU (SPAR's watch) stands in for the forearm strap: its gyro fills the forearm rate slot and its
    low-passed accelerometer (= world up at rest) the forearm up slot. No angles (one sensor gives no joint angle).
    The watch axes are not the pod axes; ``augment.imu_augment`` rotations cover that in training.
    """
    from .data import FS

    a = resample(np.hstack([seg.acc, seg.gyro]), FS, FPS)
    k = max(1, int(0.25 * FPS))
    up = np.stack([np.convolve(np.pad(a[:, j], (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), "valid")
                   for j in range(3)], axis=1)
    x = np.zeros((len(a), D_IN), dtype=np.float32)
    for t in range(len(a)):
        f, ok = imu_features({"gyro": {sensor: a[t, 3:]}, "up": {sensor: up[t]}})
        x[t] = frame_vector(None, False, f, ok)
    ex = seg.exercise if seg.exercise in CLASSES else "unknown"
    return Sample(x=x, exercise=CLASSES.index(ex), phase=np.full(len(x), -1, np.int64),
                  subject=seg.subject, source="imu", name=seg.name)
