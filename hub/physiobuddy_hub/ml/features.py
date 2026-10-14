"""Canonical per-frame features for PB-MotionNet (one definition, used live and in training).

The network *judges* movement (exercise / unknown, phase, form, compensation). Angles shown to the patient
still come only from ``SkeletonKinematics`` geometry; here they are just inputs.

Per frame (30 Hz), D = 56:
* skeleton (36): 9 joints relative to mid-shoulder, rotated into the thorax frame (X anterior, Y up,
  Z toward the affected side), divided by shoulder width -> 27; plus 9 kinematic values
  (elevation/180, apparent/180, sin/cos plane, elbow/180, rotation/90, lean_sag/45, lean_lat/45, shrug_delta).
  Left-side patients are mirrored (Z sign), so one model serves both sides.
* IMU (18): wrist, upper arm, chest x (acc/9.81, gyro/180); zeros for a missing sensor.
* mask (2): [skeleton valid, IMU valid]. Invalid blocks are zero-filled.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..core.skeleton_kin import thorax_frame
from ..datatypes import (
    L_EAR, L_ELBOW, L_HIP, L_SHOULDER, L_WRIST, NOSE, R_EAR, R_ELBOW, R_HIP, R_SHOULDER, R_WRIST, Skeleton3D,
)

FPS = 30.0
WINDOW = 64            # ~2.1 s of context
STRIDE = 16
CLASSES = ("flexion", "abduction", "external_rotation", "internal_rotation", "pendulum", "unknown")
PHASES = ("rest", "raising", "hold", "lowering")
COMP_FLAGS = ("SHRUG", "TRUNK_LEAN", "ELBOW_DRIFT", "TOO_FAST", "SHORT_ROM")
IMU_SENSORS = ("wrist", "upper_arm", "chest")

# affected-side-first joint order (mirrored for left patients)
_JOINTS = {
    "right": (NOSE, R_EAR, L_EAR, R_SHOULDER, L_SHOULDER, R_ELBOW, R_WRIST, R_HIP, L_HIP),
    "left": (NOSE, L_EAR, R_EAR, L_SHOULDER, R_SHOULDER, L_ELBOW, L_WRIST, L_HIP, R_HIP),
}
N_JOINTS = 9
D_POS = 3 * N_JOINTS
D_KIN = 9
D_SKEL = D_POS + D_KIN
D_IMU = 6 * len(IMU_SENSORS)
D_MASK = 2
D_IN = D_SKEL + D_IMU + D_MASK

_KIN_SCALE = {"elevation": 180.0, "apparent_elevation": 180.0, "elbow_flexion": 180.0, "rotation": 90.0,
              "trunk_lean_sagittal": 45.0, "trunk_lean_lateral": 45.0}


def _val(angles: Optional[dict], key: str) -> Optional[float]:
    m = (angles or {}).get(key) or {}
    v = m.get("value") if isinstance(m, dict) else None
    return None if v is None or not np.isfinite(v) else float(v)


def skeleton_features(sk: Optional[Skeleton3D], angles: Optional[dict], side: str, up_cam: np.ndarray,
                      shrug_baseline: Optional[float] = None) -> tuple:
    """-> (features (36,), valid). ``angles`` is ``CameraAngles.to_dict()`` for the same frame."""
    out = np.zeros(D_SKEL, dtype=np.float32)
    if sk is None:
        return out, False
    T = thorax_frame(sk, np.asarray(up_cam, float))
    if T is None:
        return out, False
    p, ok = sk.points, sk.valid
    origin = (p[L_SHOULDER] + p[R_SHOULDER]) / 2
    width = float(np.linalg.norm(p[R_SHOULDER] - p[L_SHOULDER]))
    if width < 0.1:
        return out, False
    z_sign = 1.0 if side == "right" else -1.0
    for k, j in enumerate(_JOINTS[side]):
        if ok[j]:
            v = T.R @ (p[j] - origin) / width
            v[2] *= z_sign
            out[3 * k:3 * k + 3] = v
    kin = out[D_POS:]
    for i, key in enumerate(("elevation", "apparent_elevation")):
        v = _val(angles, key)
        kin[i] = 0.0 if v is None else v / _KIN_SCALE[key]
    plane = _val(angles, "plane_of_elevation")
    if plane is not None:
        kin[2], kin[3] = np.sin(np.radians(plane)), np.cos(np.radians(plane))
    for i, key in ((4, "elbow_flexion"), (5, "rotation"), (6, "trunk_lean_sagittal"), (7, "trunk_lean_lateral")):
        v = _val(angles, key)
        kin[i] = 0.0 if v is None else v / _KIN_SCALE[key]
    shrug = _val(angles, "shrug_index")
    if shrug is not None and shrug_baseline:
        kin[8] = (shrug - shrug_baseline) / shrug_baseline
    np.clip(out, -5.0, 5.0, out=out)
    return out, True


def imu_features(sensors: Optional[dict]) -> tuple:
    """``sensors``: {name: (acc m/s^2 (3,), gyro deg/s (3,))} for any of IMU_SENSORS -> ((18,), valid)."""
    out = np.zeros(D_IMU, dtype=np.float32)
    if not sensors:
        return out, False
    any_ok = False
    for k, name in enumerate(IMU_SENSORS):
        s = sensors.get(name)
        if s is None:
            continue
        acc, gyro = np.asarray(s[0], float), np.asarray(s[1], float)
        if not (np.all(np.isfinite(acc)) and np.all(np.isfinite(gyro))):
            continue
        out[6 * k:6 * k + 3] = acc / 9.81
        out[6 * k + 3:6 * k + 6] = gyro / 180.0
        any_ok = True
    np.clip(out, -10.0, 10.0, out=out)
    return out, any_ok


def frame_vector(skel: np.ndarray, skel_ok: bool, imu: np.ndarray, imu_ok: bool) -> np.ndarray:
    v = np.zeros(D_IN, dtype=np.float32)
    if skel_ok:
        v[:D_SKEL] = skel
    if imu_ok:
        v[D_SKEL:D_SKEL + D_IMU] = imu
    v[-2], v[-1] = float(skel_ok), float(imu_ok)
    return v


def windows(x: np.ndarray, window: int = WINDOW, stride: int = STRIDE) -> np.ndarray:
    """(T, D) -> (N, window, D); a sequence shorter than one window is left-padded by repeating frame 0."""
    if len(x) < window:
        x = np.concatenate([np.repeat(x[:1], window - len(x), axis=0), x], axis=0)
    starts = range(0, len(x) - window + 1, stride)
    return np.stack([x[s:s + window] for s in starts])


def phase_labels(metric: np.ndarray, fps: float = FPS, start_thr: float = 25.0,
                 speed_dps: float = 8.0) -> np.ndarray:
    """Weak per-frame phase labels from the exercise metric trajectory (deg) -> PHASES indices.

    Same definition as the coach: below ``start_thr`` = rest; above it, rising faster than ``speed_dps`` =
    raising, falling faster = lowering, otherwise hold. NaN frames take the previous label.
    """
    m = np.asarray(metric, float)
    good = np.isfinite(m)
    if not good.any():
        return np.zeros(len(m), dtype=np.int64)
    m = np.interp(np.arange(len(m)), np.flatnonzero(good), m[good])
    k = max(1, int(round(0.1 * fps)))
    sm = np.convolve(np.pad(m, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    v = np.gradient(sm) * fps
    lab = np.full(len(m), PHASES.index("hold"), dtype=np.int64)
    lab[v > speed_dps] = PHASES.index("raising")
    lab[v < -speed_dps] = PHASES.index("lowering")
    lab[sm < start_thr] = PHASES.index("rest")
    return lab
