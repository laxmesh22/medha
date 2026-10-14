"""Lift 2D keypoints to metric 3D using the aligned depth image (design doc §6.2).

Rules:
* depth 0 = no data. A keypoint without enough valid depth is *invalid* (NaN), never 0.
* Depth samples far from the patient's torso depth are background and are discarded.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..datatypes import (
    Intrinsics, L_HIP, L_SHOULDER, NUM_KEYPOINTS, Pose2D, R_HIP, R_SHOULDER, Skeleton3D,
)

DeprojectFn = Callable[[float, float, float], tuple]


def pinhole_deproject(intr: Intrinsics) -> DeprojectFn:
    """Pixel (u, v) + depth z (m) -> camera-frame point. Ignores lens distortion."""

    def _fn(u: float, v: float, z: float) -> tuple:
        return ((u - intr.ppx) / intr.fx * z, (v - intr.ppy) / intr.fy * z, z)

    return _fn


def _patch(depth_m: np.ndarray, u: float, v: float, r: int) -> np.ndarray:
    h, w = depth_m.shape
    x, y = int(round(u)), int(round(v))
    if x < 0 or y < 0 or x >= w or y >= h:
        return np.empty(0, dtype=np.float32)
    return depth_m[max(0, y - r): y + r + 1, max(0, x - r): x + r + 1].ravel()


def torso_depth(pose: Pose2D, depth_m: np.ndarray, min_score: float = 0.5,
                patch_radius: int = 6) -> Optional[float]:
    """Median depth of the chest region (shoulders, hips, chest centre)."""
    torso_idx = [L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]
    ok = [i for i in torso_idx if pose.scores[i] >= min_score]
    if L_SHOULDER not in ok or R_SHOULDER not in ok:
        return None
    centre = pose.keypoints_px[ok].mean(axis=0)
    samples = []
    for u, v in list(pose.keypoints_px[ok]) + [centre]:
        p = _patch(depth_m, u, v, patch_radius)
        p = p[p > 0]
        if p.size:
            samples.append(float(np.median(p)))
    return float(np.median(samples)) if samples else None


def lift_pose(
    pose: Pose2D,
    depth_m: np.ndarray,
    intr: Intrinsics,
    deproject: Optional[DeprojectFn] = None,
    min_score: float = 0.5,
    patch_radius: int = 3,
    min_valid_frac: float = 0.3,
    near_margin_m: float = 1.0,
    far_margin_m: float = 0.35,
) -> Skeleton3D:
    """Return 3D keypoints (camera frame, metres) with a validity mask.

    ``near_margin_m``: how far in front of the torso a point may be (arm reaching toward camera).
    ``far_margin_m``: how far behind the torso a point may be (arm in extension behind the body).
    """
    deproject = deproject or pinhole_deproject(intr)
    body_z = torso_depth(pose, depth_m, min_score)
    points = np.full((NUM_KEYPOINTS, 3), np.nan, dtype=np.float64)
    valid = np.zeros(NUM_KEYPOINTS, dtype=bool)

    for i in range(NUM_KEYPOINTS):
        if pose.scores[i] < min_score:
            continue
        u, v = pose.keypoints_px[i]
        p = _patch(depth_m, u, v, patch_radius)
        if p.size == 0:
            continue
        good = p > 0
        if body_z is not None:
            good &= (p > body_z - near_margin_m) & (p < body_z + far_margin_m)
        if good.sum() < min_valid_frac * p.size:
            continue
        z = float(np.median(p[good]))
        points[i] = deproject(float(u), float(v), z)
        valid[i] = True

    return Skeleton3D(points=points, valid=valid, body_depth_m=body_z)
