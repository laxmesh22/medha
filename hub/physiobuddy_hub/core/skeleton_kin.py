"""Clinical shoulder angles from a 3D skeleton (design doc §6.3; same maths as handoff §8.3).

Thorax frame (ISB-like): Y up (superior), X anterior, Z toward the *right* shoulder.
For a left affected side, Z is mirrored so abduction / external rotation are positive on both sides.

Every output is a ``Measurement``; anything that cannot be computed is unavailable, never 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..datatypes import (
    GOOD, L_EAR, L_ELBOW, L_HIP, L_SHOULDER, L_WRIST, LOW, R_EAR, R_ELBOW, R_HIP, R_SHOULDER,
    R_WRIST, CameraAngles, Measurement, Skeleton3D,
)

SIDE_IDX = {
    "right": dict(shoulder=R_SHOULDER, elbow=R_ELBOW, wrist=R_WRIST, ear=R_EAR),
    "left": dict(shoulder=L_SHOULDER, elbow=L_ELBOW, wrist=L_WRIST, ear=L_EAR),
}

# Plane of elevation is meaningless when the arm hangs near vertical.
MIN_ELEVATION_FOR_PLANE_DEG = 15.0
# Plane windows (deg) for naming the movement.
FLEXION_PLANE = (-30.0, 30.0)
SCAPTION_PLANE = (30.0, 60.0)
ABDUCTION_PLANE = (60.0, 120.0)
# Rotation protocol: elbow at side, flexed ~90 deg.
ROT_MAX_ELEVATION_DEG = 30.0
ROT_ELBOW_FLEX_RANGE = (60.0, 120.0)
ROT_ELBOW_DRIFT_WARN_DEG = 20.0
# Trunk compensation warning thresholds (provisional, tune with validation data).
TRUNK_LEAN_WARN_DEG = 10.0


def _unit(v: np.ndarray) -> Optional[np.ndarray]:
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n < 1e-6:
        return None
    return v / n


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b), -1.0, 1.0))))


@dataclass
class ThoraxFrame:
    R: np.ndarray        # 3x3, rows = thorax X (anterior), Y (up), Z (right) in camera coords
    from_hips: bool      # False -> Y axis taken from gravity (hips not visible)

    def to_thorax(self, v_cam: np.ndarray) -> np.ndarray:
        return self.R @ v_cam


def thorax_frame(sk: Skeleton3D, up_cam: np.ndarray) -> Optional[ThoraxFrame]:
    """Build the thorax frame from shoulders (+ hips). ``up_cam`` = world up in camera coords."""
    p, ok = sk.points, sk.valid
    if not (ok[L_SHOULDER] and ok[R_SHOULDER]):
        return None
    sh_mid = (p[L_SHOULDER] + p[R_SHOULDER]) / 2
    from_hips = bool(ok[L_HIP] and ok[R_HIP])
    if from_hips:
        y = _unit(sh_mid - (p[L_HIP] + p[R_HIP]) / 2)
    else:
        y = _unit(up_cam)
    z_raw = p[R_SHOULDER] - p[L_SHOULDER]
    if y is None:
        return None
    z = _unit(z_raw - np.dot(z_raw, y) * y)
    if z is None:
        return None
    x = np.cross(y, z)  # right-handed: anterior
    return ThoraxFrame(R=np.vstack([x, y, z]), from_hips=from_hips)


class SkeletonKinematics:
    """Stateful wrapper: holds per-session baselines (shrug) and the affected side."""

    def __init__(self, side: str = "right"):
        if side not in SIDE_IDX:
            raise ValueError("side must be 'right' or 'left'")
        self.side = side
        self.z_sign = 1.0 if side == "right" else -1.0
        self.shrug_baseline: Optional[float] = None

    def set_shrug_baseline(self, value: Optional[float]) -> None:
        self.shrug_baseline = value

    def compute(self, sk: Skeleton3D, up_cam: np.ndarray) -> CameraAngles:
        idx = SIDE_IDX[self.side]
        p, ok = sk.points, sk.valid
        flags: list = []
        na = Measurement.unavailable

        up_cam = _unit(np.asarray(up_cam, dtype=float))
        T = thorax_frame(sk, up_cam)
        if T is None:
            reason = "shoulders not visible"
            return CameraAngles(self.side, None, na(reason), na(reason), na(reason), na(reason),
                                na(reason), na(reason), na(reason), na(reason), ["NO_THORAX"])
        base_q = GOOD if T.from_hips else LOW
        if not T.from_hips:
            flags.append("THORAX_FROM_GRAVITY")

        # --- trunk lean: world up expressed in thorax frame -------------------------------
        up_t = T.to_thorax(up_cam)
        if T.from_hips:
            lean_sag = Measurement(float(np.degrees(np.arctan2(-up_t[0], up_t[1]))), GOOD)
            lean_lat = Measurement(
                float(np.degrees(np.arctan2(-up_t[2] * self.z_sign, up_t[1]))), GOOD)
            if abs(lean_sag.value) > TRUNK_LEAN_WARN_DEG:
                flags.append("TRUNK_LEAN_SAGITTAL")
            if abs(lean_lat.value) > TRUNK_LEAN_WARN_DEG:
                flags.append("TRUNK_LEAN_LATERAL")
        else:
            lean_sag = na("hips not visible")
            lean_lat = na("hips not visible")

        # --- humerus --------------------------------------------------------------------
        if not (ok[idx["shoulder"]] and ok[idx["elbow"]]):
            reason = "upper arm not visible"
            elev = app = plane = na(reason)
            movement = None
            u = None
        else:
            u_cam = _unit(p[idx["elbow"]] - p[idx["shoulder"]])
            u = T.to_thorax(u_cam)
            u[2] *= self.z_sign
            elev = Measurement(_angle_deg(u, np.array([0.0, -1.0, 0.0])), base_q)
            app = Measurement(_angle_deg(u_cam, -up_cam), GOOD)
            if elev.value < MIN_ELEVATION_FOR_PLANE_DEG:
                plane = na("arm near side")
                movement = "rest"
            else:
                plane = Measurement(float(np.degrees(np.arctan2(u[2], u[0]))), base_q)
                movement = _name_movement(plane.value)

        # --- elbow + rotation (ER/IR, elbow-at-side protocol) -------------------------------
        rot = na("forearm not visible")
        elbow = na("forearm not visible")
        if u is not None and ok[idx["wrist"]]:
            f_cam = _unit(p[idx["wrist"]] - p[idx["elbow"]])
            if f_cam is not None:
                f = T.to_thorax(f_cam)
                f[2] *= self.z_sign
                elbow = Measurement(_angle_deg(u, f), base_q)
                rot = self._rotation(elev, elbow, f, flags)

        # --- shrug: ear-shoulder distance normalised by shoulder width ---------------------
        shrug = na("ear/shoulder not visible")
        if ok[idx["ear"]] and ok[idx["shoulder"]]:
            width = float(np.linalg.norm(p[R_SHOULDER] - p[L_SHOULDER]))
            if width > 0.15:
                s = float(np.linalg.norm(p[idx["ear"]] - p[idx["shoulder"]])) / width
                shrug = Measurement(s, GOOD)
                if self.shrug_baseline and (self.shrug_baseline - s) / self.shrug_baseline > 0.12:
                    flags.append("SHRUG")

        if (elev.value is not None and app.value is not None
                and abs(app.value - elev.value) > TRUNK_LEAN_WARN_DEG):
            flags.append("APPARENT_TRUE_GAP")

        return CameraAngles(self.side, movement, elev, app, plane, elbow, rot,
                            lean_sag, lean_lat, shrug, flags)

    @staticmethod
    def _rotation(elev: Measurement, elbow: Measurement, f: np.ndarray, flags: list) -> Measurement:
        if elev.value is None or elev.value > ROT_MAX_ELEVATION_DEG:
            return Measurement.unavailable("rotation needs elbow at side")
        if not (ROT_ELBOW_FLEX_RANGE[0] <= elbow.value <= ROT_ELBOW_FLEX_RANGE[1]):
            return Measurement.unavailable("rotation needs elbow ~90 deg")
        horiz = float(np.hypot(f[0], f[2]))
        if horiz < 0.5:
            return Measurement.unavailable("forearm not horizontal")
        if elev.value > ROT_ELBOW_DRIFT_WARN_DEG:
            flags.append("ELBOW_DRIFT")
        # 0 = forearm pointing anterior; + toward lateral = external rotation
        return Measurement(float(np.degrees(np.arctan2(f[2], f[0]))), elev.quality)


def _name_movement(plane_deg: float) -> str:
    if FLEXION_PLANE[0] <= plane_deg < FLEXION_PLANE[1]:
        return "flexion"
    if SCAPTION_PLANE[0] <= plane_deg < SCAPTION_PLANE[1]:
        return "scaption"
    if ABDUCTION_PLANE[0] <= plane_deg <= ABDUCTION_PLANE[1]:
        return "abduction"
    if abs(plane_deg) >= 150.0:
        return "extension"
    return "other"
