"""Virtual straps: the device's three BNO085s (upper arm, forearm, trunk) simulated from a skeleton.

Segment orientations come from the joints (thorax from shoulders + hips, humerus = swing from rest plus the axial
twist the forearm reveals when the elbow is bent, forearm = humerus turned by the elbow angle). Each strap is then
worn the way real people wear it: rotated around the limb by up to ``misplace_deg``, tilted a little, with its own
yaw reference, orientation noise and gyro bias. Calibration runs the hub's real ``StrapCalibration`` on a simulated
N-pose (with posture error) and, in ``p_forward_raise`` of sessions, on a simulated forward raise. So the network is
trained on exactly what ``core.strap_kin`` will compute live, including its calibration errors.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from physiobuddy_hub.core.skeleton_kin import SIDE_IDX, thorax_frame
from physiobuddy_hub.core.strap_kin import (
    DOWN, SENSORS, StrapCalibration, StrapKinematics, align, axis_angle, matrix_to_quat, nominal_mount,
)

from .datasets.common import to_skeleton3d

FPS = 30.0
_Y_UP_TO_Z_UP = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])   # (x, y_up, z) -> (x, -z, y)


def _world_basis(up_cam: np.ndarray) -> np.ndarray:
    """Rows = world X, Y (up), Z in camera coordinates."""
    y = np.asarray(up_cam, float) / np.linalg.norm(up_cam)
    x = np.cross(y, [0.0, 0.0, 1.0])
    if np.linalg.norm(x) < 1e-6:
        x = np.cross(y, [1.0, 0.0, 0.0])
    x /= np.linalg.norm(x)
    return np.vstack([x, y, np.cross(x, y)])


def _smoothstep(a: float, b: float, v: float) -> float:
    t = float(np.clip((v - a) / (b - a), 0.0, 1.0))
    return t * t * (3 - 2 * t)


def segments_from_points(points: np.ndarray, side: str, up_cam: np.ndarray) -> Optional[dict]:
    """(T, 17, 3) camera-frame joints -> {sensor: (T, 3, 3) segment -> world (Y up)}, or None if unusable.
    Frames where the thorax or arm is missing repeat the previous frame."""
    idx = SIDE_IDX[side]
    W = _world_basis(up_cam)
    out = {s: np.zeros((len(points), 3, 3)) for s in SENSORS}
    last = None
    ez = np.array([0.0, 0.0, 1.0])
    for t, p in enumerate(points):
        frames = None
        if np.all(np.isfinite(p[[idx["shoulder"], idx["elbow"], idx["wrist"]]])):
            T = thorax_frame(to_skeleton3d(p), up_cam)
            if T is not None:
                u = T.R @ (p[idx["elbow"]] - p[idx["shoulder"]])
                f = T.R @ (p[idx["wrist"]] - p[idx["elbow"]])
                if np.linalg.norm(u) > 1e-6 and np.linalg.norm(f) > 1e-6:
                    u, f = u / np.linalg.norm(u), f / np.linalg.norm(f)
                    R_arm = align(DOWN, u)                         # swing from rest, no twist
                    flex = float(np.degrees(np.arccos(np.clip(np.dot(u, f), -1, 1))))
                    f_perp = f - np.dot(f, u) * u
                    x_now = R_arm @ np.array([1.0, 0, 0])
                    if np.linalg.norm(f_perp) > 1e-3:
                        f_perp /= np.linalg.norm(f_perp)
                        twist = np.arctan2(np.dot(u, np.cross(x_now, f_perp)), np.dot(x_now, f_perp))
                        R_arm = axis_angle(u, _smoothstep(30.0, 50.0, flex) * twist) @ R_arm
                    R_fore = R_arm @ axis_angle(ez, np.radians(flex))
                    to_world = W @ T.R.T
                    frames = {"trunk": to_world, "upper_arm": to_world @ R_arm, "forearm": to_world @ R_fore}
        if frames is None:
            if last is None:
                continue
            frames = last
        for s in SENSORS:
            out[s][t] = frames[s]
        last = frames
    if last is None:
        return None
    first = next(t for t in range(len(points)) if np.abs(out["trunk"][t]).sum() > 0)
    for s in SENSORS:
        out[s][:first] = out[s][first]
    return out


def _gyro(R: np.ndarray, fps: float) -> np.ndarray:
    """(T, 3, 3) sensor -> world rotations -> body-frame angular rate (T, 3) in deg/s."""
    dR = np.gradient(R, 1.0 / fps, axis=0)
    Wm = np.einsum("nji,njk->nik", R, dR)                     # R^T dR/dt (skew in theory)
    return np.degrees(np.stack([Wm[:, 2, 1] - Wm[:, 1, 2], Wm[:, 0, 2] - Wm[:, 2, 0], Wm[:, 1, 0] - Wm[:, 0, 1]], 1) / 2)


def _small_rot(rng, deg: float) -> np.ndarray:
    return axis_angle(rng.normal(size=3), np.radians(rng.normal(0, deg)))


class Wearer:
    """One session's straps: true mounts and each sensor's yaw reference."""

    def __init__(self, side: str, rng, misplace_deg: float = 15.0, tilt_deg: float = 4.0):
        self.side = side
        self.mount, self.yaw = {}, {}
        for s in SENSORS:
            spin = rng.uniform(-misplace_deg, misplace_deg) if s != "trunk" else rng.uniform(-10.0, 10.0)
            E = axis_angle([0, 1.0, 0], np.radians(spin)) @ _small_rot(rng, tilt_deg)   # in segment axes
            self.mount[s] = nominal_mount(s, side) @ E.T                                 # segment -> sensor
            self.yaw[s] = axis_angle([0, 0, 1.0], rng.uniform(-np.pi, np.pi))

    def sensor_rotations(self, segs: dict, rng=None, noise_deg: float = 0.4) -> dict:
        """{sensor: (T,3,3) segment -> world(Y up)} -> {sensor: (T,3,3) sensor -> its Z-up world}."""
        out = {}
        for s, Rseg in segs.items():
            R = np.einsum("ij,njk,kl->nil", self.yaw[s] @ _Y_UP_TO_Z_UP, Rseg, self.mount[s].T)
            if rng is not None and noise_deg > 0:
                R = np.stack([r @ _small_rot(rng, noise_deg) for r in R])
            out[s] = R
        return out


def simulate_calibration(wearer: Wearer, trunk_world: np.ndarray, rng, p_forward_raise: float = 0.6) -> StrapCalibration:
    """N-pose (upright, arms at the sides, a little posture error) -> ``StrapCalibration.from_npose``; then, with
    probability ``p_forward_raise``, a straight-arm forward raise -> ``refine_with_forward_raise``."""
    # upright trunk with the session's heading
    fwd = trunk_world[:, 0].copy()
    fwd[1] = 0.0
    fwd /= np.linalg.norm(fwd)
    up = np.array([0.0, 1.0, 0.0])
    trunk0 = np.stack([fwd, up, np.cross(fwd, up)], axis=1) @ _small_rot(rng, 2.0)
    arm0 = trunk0 @ axis_angle([0, 0, 1.0], np.radians(rng.normal(0, 3))) @ axis_angle(
        [1.0, 0, 0], np.radians(rng.uniform(0, 6) * (1 if wearer.side == "right" else -1)))
    fore0 = arm0 @ axis_angle([0, 0, 1.0], np.radians(rng.uniform(0, 8)))
    n = 40
    segs = {"trunk": np.repeat(trunk0[None], n, 0), "upper_arm": np.repeat(arm0[None], n, 0),
            "forearm": np.repeat(fore0[None], n, 0)}
    R = wearer.sensor_rotations(segs, rng)
    cal = StrapCalibration.from_npose(wearer.side, {s: [matrix_to_quat(r) for r in R[s]] for s in SENSORS})
    if rng.random() < p_forward_raise:
        m = 60
        ang = np.radians(np.linspace(0, 100, m))
        wob = np.radians(rng.normal(0, 4)) * np.sin(np.linspace(0, np.pi, m))
        arm = np.stack([trunk0 @ axis_angle([0, 0, 1.0], a) @ axis_angle([1.0, 0, 0], w) for a, w in zip(ang, wob)])
        segs = {"upper_arm": arm, "forearm": arm, "trunk": np.repeat(trunk0[None], m, 0)}
        R = wearer.sensor_rotations(segs)                 # gyro from the clean motion, then sensor noise
        cal.refine_with_forward_raise({s: _gyro(R[s], FPS) + rng.normal(0, 1.0, (m, 3)) for s in ("upper_arm", "forearm")})
    return cal


def strap_frames(segs: dict, side: str, rng, fps: float = FPS, wearer: Optional[Wearer] = None,
                 calibration: Optional[StrapCalibration] = None, drop: tuple = ()) -> list:
    """Segment orientations -> per-frame strap dicts for ``imu_features`` ({"angles", "gyro", "up"}).
    ``drop`` lists sensors to leave out (a strap not worn)."""
    wearer = wearer or Wearer(side, rng)
    cal = calibration or simulate_calibration(wearer, segs["trunk"][0], rng)
    clean = wearer.sensor_rotations(segs)
    gyro = {s: _gyro(clean[s], fps) + rng.normal(0, 0.6, 3) + rng.normal(0, 1.0, (len(clean[s]), 3)) for s in SENSORS}
    R = wearer.sensor_rotations(segs, rng)                # orientation noise (not differentiated)
    kin = StrapKinematics(cal)
    keep = [s for s in SENSORS if s not in drop]
    out = []
    for t in range(len(R["trunk"])):
        q = {s: matrix_to_quat(R[s][t]) for s in keep}
        out.append({"angles": kin.compute(q).to_dict(),
                    "gyro": {s: cal.gyro_in_segment(s, gyro[s][t]) for s in keep},
                    "up": {s: cal.up_in_segment(s, q[s]) for s in keep}})
    return out
