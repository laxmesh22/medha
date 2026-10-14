"""Synthetic patient for developing without the camera (``run --sim``).

The animated 3D skeleton is projected to 2D keypoints and painted into a synthetic depth image, so the
*real* depth-lift, plausibility and kinematics code runs end to end. Cycle (36 s): held flexion rep ->
abduction with a deliberate trunk lean -> held external rotation -> hand hidden (camera unavailable).
"""

from __future__ import annotations

import time

import numpy as np

from .datatypes import (
    CameraFrame, Intrinsics, L_EAR, L_ELBOW, L_EYE, L_HIP, L_SHOULDER, L_WRIST, NOSE,
    NUM_KEYPOINTS, Pose2D, R_EAR, R_ELBOW, R_EYE, R_HIP, R_SHOULDER, R_WRIST,
)

INTR = Intrinsics(848, 480, 425.0, 425.0, 424.0, 240.0)
DIST = 2.2
FPS = 30.0


def _body_to_cam(v):
    # thorax frame (X anterior, Y up, Z right) of a patient facing the camera -> RealSense frame
    return np.array([-v[2], -v[1], -v[0]]) + np.array([0.0, -0.2, DIST])


def _arm(theta_deg, plane_deg):
    t, p = np.radians(theta_deg), np.radians(plane_deg)
    return np.array([np.sin(t) * np.cos(p), -np.cos(t), np.sin(t) * np.sin(p)])


def _rep(t, rise=2.5, hold=5.5, lower=2.5):
    """Smooth rep profile 0 -> 1 (raise), 1 (hold), 1 -> 0 (lower)."""
    s = lambda x: 0.5 - 0.5 * np.cos(np.pi * np.clip(x, 0, 1))  # noqa: E731
    if t < rise:
        return s(t / rise)
    if t < rise + hold:
        return 1.0 - 0.01 * np.sin(3 * t)  # tiny natural wobble while holding
    return 1.0 - s((t - rise - hold) / lower)


CYCLE_S = 36.0


def sim_skeleton(t: float):
    """Return (points_cam (17,3), visible mask) for time t.

    Cycle: good flexion rep with a 5.5 s hold -> abduction with trunk lean + shrug (a rep that needs
    fixing) -> external rotation with hold -> behind-back reach (wrist hidden: camera unavailable).
    """
    phase = t % CYCLE_S
    elev, plane, shrug, lean = 0.0, 0.0, 0.0, 0.0
    fore = None
    hide_wrist = False
    if phase < 11.5:                                 # flexion to ~135, held
        elev, plane = 135 * _rep(phase), 0
    elif phase < 23:                                 # abduction to ~115 with trunk lean + shrug
        k = _rep(phase - 11.5)
        elev, plane, lean, shrug = 115 * k, 90, -14 * k, 0.05 * k
    elif phase < 32:                                 # ER at side, elbow 90, held
        er = 55 * _rep(phase - 23, rise=2.0, hold=5.0, lower=1.5)
        fore = np.array([np.cos(np.radians(er)), 0, np.sin(np.radians(er))])
    else:                                            # behind-back reach: wrist hidden from camera
        elev, plane, hide_wrist = 25, 180, True

    a = np.radians(lean)  # lateral lean (+ toward right)
    R = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    pts = {
        R_SHOULDER: np.array([0, shrug, 0.18]), L_SHOULDER: np.array([0, 0, -0.18]),
        R_HIP: np.array([0, -0.5, 0.12]), L_HIP: np.array([0, -0.5, -0.12]),
        R_EAR: np.array([0, 0.22, 0.08]), L_EAR: np.array([0, 0.22, -0.08]),
        R_EYE: np.array([0.08, 0.25, 0.035]), L_EYE: np.array([0.08, 0.25, -0.035]),
        NOSE: np.array([0.1, 0.2, 0.0]),
    }
    u = _arm(elev, plane)
    pts[R_ELBOW] = pts[R_SHOULDER] + 0.30 * u
    pts[R_WRIST] = pts[R_ELBOW] + 0.26 * (fore if fore is not None else u)
    pts[L_ELBOW] = pts[L_SHOULDER] + 0.30 * np.array([0, -1.0, 0])
    pts[L_WRIST] = pts[L_ELBOW] + 0.26 * np.array([0, -1.0, 0])

    out = np.full((NUM_KEYPOINTS, 3), np.nan)
    vis = np.zeros(NUM_KEYPOINTS, dtype=bool)
    for i, p in pts.items():
        out[i] = _body_to_cam(R @ p)
        vis[i] = True
    if hide_wrist:
        vis[R_WRIST] = False
    return out, vis


class SimSource:
    def __init__(self):
        self.t0 = time.time()
        self.n = 0
        self.info = {"device": "simulator", "source": "sim", "resolution": [INTR.width, INTR.height], "fps": FPS}
        self.current = None

    def start(self):
        pass

    def stop(self):
        pass

    def latest(self, timeout: float = 1.0):
        time.sleep(1.0 / FPS)
        self.n += 1
        t = time.time() - self.t0
        pts, vis = sim_skeleton(t)
        depth = np.zeros((INTR.height, INTR.width), np.float32)
        depth[:, :] = DIST + 1.5                      # back wall
        u = pts[:, 0] / pts[:, 2] * INTR.fx + INTR.ppx
        v = pts[:, 1] / pts[:, 2] * INTR.fy + INTR.ppy
        # torso slab, then each visible joint painted at its own depth
        top, bot = int(np.nanmin(v[[L_SHOULDER, R_SHOULDER]])), int(np.nanmax(v[[L_HIP, R_HIP]]))
        left, right = int(np.nanmin(u[[R_SHOULDER, R_HIP]])), int(np.nanmax(u[[L_SHOULDER, L_HIP]]))
        depth[max(top, 0):bot, max(left, 0):right] = DIST
        for i in range(NUM_KEYPOINTS):
            if vis[i] and 0 <= u[i] < INTR.width and 0 <= v[i] < INTR.height:
                x, y = int(u[i]), int(v[i])
                depth[max(y - 5, 0):y + 6, max(x - 5, 0):x + 6] = pts[i, 2]
        kp = np.stack([u, v], axis=1)
        scores = np.where(vis, 0.9, 0.05)
        self.current = Pose2D(np.nan_to_num(kp), scores)
        return CameraFrame(color=np.zeros((INTR.height, INTR.width, 3), np.uint8), depth_m=depth,
                           intrinsics=INTR, timestamp_ms=time.time() * 1000, frame_number=self.n)


class SimPose:
    name = "simulator"

    def __init__(self, source: SimSource):
        self.source = source

    def __call__(self, bgr):
        return self.source.current
