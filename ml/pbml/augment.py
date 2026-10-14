"""Augmentations on raw camera-frame skeletons (T, 17, 3) and IMU streams, applied *before* feature extraction
so the hub geometry recomputes every angle consistently.

The key one is ``restrict_rom``: public data is from healthy people with full range; frozen-shoulder patients
reach 45-85 % of it. Rotating the arm about the shoulder toward rest turns a 160 deg flexion into a believable
90 deg one, with correct forearm/elbow geometry, so the classifier learns "flexion" from patient-like reps.
"""

from __future__ import annotations

import numpy as np

from physiobuddy_hub.core.skeleton_kin import SIDE_IDX, thorax_frame

from .datasets.common import to_skeleton3d


def _rodrigues(axis: np.ndarray, angle: float) -> np.ndarray:
    k = axis / np.linalg.norm(axis)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K


def restrict_rom(points: np.ndarray, side: str, alpha: float, up_cam: np.ndarray) -> np.ndarray:
    """Scale humerothoracic elevation by ``alpha`` (0-1) by rotating elbow + wrist about the shoulder."""
    idx = SIDE_IDX[side]
    s, e, w = idx["shoulder"], idx["elbow"], idx["wrist"]
    out = points.copy()
    for t, p in enumerate(points):
        if not np.all(np.isfinite(p[[s, e]])):
            continue
        T = thorax_frame(to_skeleton3d(p), up_cam)
        if T is None:
            continue
        down = -T.R[1]                                  # thorax "down" in camera coords
        u = p[e] - p[s]
        u_n = u / np.linalg.norm(u)
        theta = float(np.arccos(np.clip(np.dot(u_n, down), -1, 1)))
        axis = np.cross(u_n, down)
        if theta < 1e-3 or np.linalg.norm(axis) < 1e-6:
            continue
        R = _rodrigues(axis, (1 - alpha) * theta)
        out[t, e] = p[s] + R @ u
        if np.all(np.isfinite(p[w])):
            out[t, w] = p[s] + R @ (p[w] - p[s])
    return out


def time_warp(points: np.ndarray, factor: float) -> np.ndarray:
    """Resample in time: factor > 1 = slower (longer). NaNs follow the nearest source frame."""
    T = len(points)
    n = max(2, int(round(T * factor)))
    src = np.linspace(0, T - 1, n)
    flat = points.reshape(T, -1)
    out = np.empty((n, flat.shape[1]))
    for j in range(flat.shape[1]):
        col = flat[:, j]
        good = np.isfinite(col)
        out[:, j] = np.interp(src, np.flatnonzero(good), col[good]) if good.sum() >= 2 else np.nan
    nearest = np.clip(np.round(src).astype(int), 0, T - 1)
    out[~np.isfinite(flat[nearest])] = np.nan
    return out.reshape(n, *points.shape[1:])


def viewpoint(points: np.ndarray, up_cam: np.ndarray, yaw_deg: float, tilt_deg: float) -> tuple:
    """Patient turned by ``yaw`` about the vertical through the body; camera pitched by ``tilt``.

    Returns (points, up_cam): a camera tilt also changes where "up" is in camera coordinates.
    """
    up = np.asarray(up_cam, float) / np.linalg.norm(up_cam)
    centre = np.nanmean(points.reshape(-1, 3), axis=0)
    Ry = _rodrigues(up, np.radians(yaw_deg))
    Rt = _rodrigues(np.array([1.0, 0.0, 0.0]), np.radians(tilt_deg))
    out = ((points - centre) @ Ry.T + centre) @ Rt.T
    return out, Rt @ up


def jitter(points: np.ndarray, rng, sigma_m: float = 0.008, depth_m: float = 0.02) -> np.ndarray:
    """Per-joint Gaussian noise plus D455-like depth noise (uniform +-depth_m along Z)."""
    noise = rng.normal(0, sigma_m, points.shape)
    noise[..., 2] += rng.uniform(-depth_m, depth_m, points.shape[:-1])
    return points + noise


def occlude(points: np.ndarray, rng, p_joint: float = 0.02, burst_p: float = 0.3,
            burst_len: tuple = (5, 30)) -> np.ndarray:
    """Random single-joint dropouts plus (with ``burst_p``) one burst where the arm disappears."""
    out = points.copy()
    mask = rng.random(points.shape[:2]) < p_joint
    out[mask] = np.nan
    if rng.random() < burst_p and len(points) > burst_len[0]:
        n = int(rng.integers(burst_len[0], min(burst_len[1], len(points)) + 1))
        s = int(rng.integers(0, len(points) - n + 1))
        joints = rng.choice([7, 8, 9, 10], size=int(rng.integers(1, 3)), replace=False)
        out[s:s + n, joints] = np.nan
    return out


def imu_augment(acc: np.ndarray, gyro: np.ndarray, rng, mount_deg: float = 15.0) -> tuple:
    """Strap mounting rotation, gyro bias, amplitude scaling and noise (units unchanged)."""
    axis = rng.normal(size=3)
    R = _rodrigues(axis, np.radians(rng.uniform(-mount_deg, mount_deg)))
    s = rng.uniform(0.9, 1.1)
    acc2 = acc @ R.T + rng.normal(0, 0.1, acc.shape)
    gyro2 = s * (gyro @ R.T) + rng.normal(0, 1.0, 3) + rng.normal(0, 1.0, gyro.shape)
    return acc2, gyro2


def random_skeleton_aug(points: np.ndarray, side: str, up_cam: np.ndarray, rng, rom: bool = True) -> tuple:
    """The training-time chain: ROM restriction (50 %) -> time warp -> viewpoint -> jitter -> occlusion."""
    alpha = 1.0
    if rom and rng.random() < 0.5:
        alpha = float(rng.uniform(0.45, 0.85))
        points = restrict_rom(points, side, alpha, up_cam)
    points = time_warp(points, float(rng.uniform(0.75, 1.35)))
    points, up_cam = viewpoint(points, up_cam, float(rng.uniform(-20, 20)), float(rng.uniform(-8, 8)))
    points = occlude(jitter(points, rng), rng)
    return points, up_cam, alpha
