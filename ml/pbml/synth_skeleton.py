"""Synthetic skeleton (+ paired virtual wrist IMU) sequences for code-path checks and unit tests.

Parametric people (shoulder width, limb lengths, speed, ROM, camera distance/yaw) doing the PB-MotionNet
classes, with ground-truth phases and scripted compensations. Numbers from models trained on this say
nothing about real performance; it exists so training, ONNX export and the live hub can be tested today.
"""

from __future__ import annotations

import numpy as np

from physiobuddy_hub.datatypes import (
    L_ANKLE, L_EAR, L_ELBOW, L_HIP, L_KNEE, L_SHOULDER, L_WRIST, NOSE, R_ANKLE, R_EAR, R_ELBOW, R_HIP, R_KNEE,
    R_SHOULDER, R_WRIST,
)

from .datasets.common import SkeletonSequence

FPS = 30.0
G = 9.81
CLASSES = ("flexion", "abduction", "external_rotation", "internal_rotation", "pendulum", "unknown")
COMPS = {"flexion": ("SHRUG", "TOO_FAST"), "abduction": ("TRUNK_LEAN", "SHRUG"),
         "external_rotation": ("ELBOW_DRIFT",), "internal_rotation": ("ELBOW_DRIFT",)}
COMP_FLAGS = ("SHRUG", "TRUNK_LEAN", "ELBOW_DRIFT", "TOO_FAST", "SHORT_ROM")


def _rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def subject_params(rng) -> dict:
    return {"half_w": rng.uniform(0.16, 0.21), "upper": rng.uniform(0.27, 0.33), "fore": rng.uniform(0.23, 0.28),
            "speed": rng.uniform(0.75, 1.3), "rom": rng.uniform(0.55, 1.0), "dist": rng.uniform(1.9, 2.7),
            "yaw": rng.uniform(-15, 15), "hold": rng.uniform(1.0, 5.0)}


def _rep_profile(rng, p, n_reps, fast=False) -> tuple:
    """Normalised 0..1 amplitude over time + phase labels (0 rest, 1 raising, 2 hold, 3 lowering)."""
    a, ph = [], []
    for _ in range(n_reps):
        rest = int(FPS * rng.uniform(0.6, 1.4))
        up = int(FPS * (rng.uniform(0.35, 0.6) if fast else rng.uniform(1.4, 2.4) / p["speed"]))
        hold = 0 if fast else int(FPS * p["hold"] * rng.uniform(0.8, 1.2))
        down = int(FPS * (rng.uniform(0.35, 0.6) if fast else rng.uniform(1.4, 2.4) / p["speed"]))
        a += [0.0] * rest + list(0.5 - 0.5 * np.cos(np.linspace(0, np.pi, up))) + [1.0] * hold \
            + list(0.5 + 0.5 * np.cos(np.linspace(0, np.pi, down)))
        ph += [0] * rest + [1] * up + [2] * hold + [3] * down
    tail = int(FPS * rng.uniform(0.6, 1.2))
    return np.array(a + [0.0] * tail), np.array(ph + [0] * tail)


def _unknown_motion(rng, n):
    """Arm (u, f) direction sequences for everyday non-exercise movements, in the body frame."""
    t = np.arange(n) / FPS
    kind = rng.choice(["scratch_head", "wave", "pocket", "cross_reach", "swing", "stand"])
    u = np.tile([0.0, -1.0, 0.0], (n, 1))
    f = u.copy()
    env = np.clip(np.minimum(t, t[-1] - t) / 0.8, 0, 1)[:, None]
    if kind == "scratch_head":
        u = np.array([0.3, 0.6, 0.75]) * env + u * (1 - env)
        f = np.array([-0.2, 0.3, -0.93]) * env + f * (1 - env)
    elif kind == "wave":
        u = np.array([0.2, -0.2, 0.96]) * env + u * (1 - env)
        osc = np.sin(2 * np.pi * 2.0 * t)[:, None]
        f = (np.array([0.0, 1.0, 0.0]) + 0.5 * osc * np.array([0, 0, 1.0])) * env + f * (1 - env)
    elif kind == "pocket":
        u = np.array([-0.3, -0.95, 0.1]) * env + u * (1 - env)
        f = np.array([0.5, -0.8, -0.3]) * env + f * (1 - env)
    elif kind == "cross_reach":
        u = np.array([0.8, -0.3, -0.5]) * env + u * (1 - env)
        f = np.array([0.6, -0.1, -0.8]) * env + f * (1 - env)
    elif kind == "swing":
        s = 0.5 * np.sin(2 * np.pi * 0.9 * t)[:, None]
        u = np.hstack([s, -np.ones((n, 1)), np.zeros((n, 1))])
        f = u.copy()
    u = u / np.linalg.norm(u, axis=1, keepdims=True)
    f = f / np.linalg.norm(f, axis=1, keepdims=True)
    return u, f, str(kind)


def make_sequence(exercise: str, side: str, rng, p: dict, comp=None, n_reps: int = 3, subject: str = "SYN"):
    """-> (SkeletonSequence with meta phase/comp/imu, paired wrist IMU (acc m/s^2, gyro deg/s))."""
    zs = 1.0 if side == "right" else -1.0
    fast = comp == "TOO_FAST"
    if exercise == "unknown":
        n = int(FPS * rng.uniform(5, 9))
        u, f, kind = _unknown_motion(rng, n)
        amp, phase = np.zeros(n), np.full(n, -1)
    else:
        amp, phase = _rep_profile(rng, p, n_reps, fast)
        n = len(amp)
        u = np.zeros((n, 3)); f = np.zeros((n, 3))
        kind = exercise
    trunk = [np.eye(3)] * n
    shrug = np.zeros(n)
    peak = {"flexion": 160, "abduction": 150, "external_rotation": 60, "internal_rotation": 70, "pendulum": 25}
    for i in range(n):
        if exercise == "unknown":
            continue
        a = amp[i] * p["rom"] * np.radians(peak[exercise])
        if exercise == "flexion":
            u[i] = (np.sin(a), -np.cos(a), 0); f[i] = u[i]
        elif exercise == "abduction":
            u[i] = (0, -np.cos(a), np.sin(a)); f[i] = u[i]
        elif exercise in ("external_rotation", "internal_rotation"):
            r = a if exercise == "external_rotation" else -a
            drift = np.radians(30) * amp[i] if comp == "ELBOW_DRIFT" else 0.0
            u[i] = (0, -np.cos(drift), np.sin(drift))
            f[i] = (np.cos(r), 0, np.sin(r))
        elif exercise == "pendulum":
            ph = 2 * np.pi * 0.8 * i / FPS
            u[i] = (np.sin(a) * np.cos(ph), -np.cos(a), np.sin(a) * np.sin(ph)); f[i] = u[i]
            trunk[i] = _rz(-np.radians(55))           # bent forward
        if comp == "SHRUG":
            shrug[i] = 0.045 * amp[i]
        if comp == "TRUNK_LEAN":
            trunk[i] = _rx(-zs * np.radians(16) * amp[i])  # lean away from the moving arm
    if exercise == "pendulum":
        # arm hangs with gravity: express world-hanging directions in the bent trunk frame
        u = np.array([trunk[i].T @ u[i] for i in range(n)]); f = u.copy()
    pts_body = np.zeros((n, 17, 3))
    hw = p["half_w"]
    for i in range(n):
        base = {NOSE: (0.1, 0.22, 0), L_EAR: (0, 0.2, -0.08), R_EAR: (0, 0.2, 0.08),
                L_SHOULDER: (0, 0, -hw), R_SHOULDER: (0, 0, hw), L_HIP: (0, -0.5, -0.12), R_HIP: (0, -0.5, 0.12),
                L_KNEE: (0, -0.95, -0.12), R_KNEE: (0, -0.95, 0.12), L_ANKLE: (0, -1.4, -0.12),
                R_ANKLE: (0, -1.4, 0.12)}
        P = {k: np.array(v, float) for k, v in base.items()}
        aff_sh, aff_el, aff_wr = (R_SHOULDER, R_ELBOW, R_WRIST) if side == "right" else (L_SHOULDER, L_ELBOW, L_WRIST)
        oth_sh, oth_el, oth_wr = (L_SHOULDER, L_ELBOW, L_WRIST) if side == "right" else (R_SHOULDER, R_ELBOW, R_WRIST)
        P[aff_sh] = P[aff_sh] + np.array([0, shrug[i], 0])
        m = np.array([1, 1, zs])
        P[aff_el] = P[aff_sh] + p["upper"] * (u[i] * m)
        P[aff_wr] = P[aff_el] + p["fore"] * (f[i] * m)
        P[oth_el] = P[oth_sh] + p["upper"] * np.array([0, -1.0, 0])
        P[oth_wr] = P[oth_el] + p["fore"] * np.array([0, -1.0, 0])
        hip_c = (P[L_HIP] + P[R_HIP]) / 2
        for k in P:
            if k in (L_KNEE, R_KNEE, L_ANKLE, R_ANKLE, L_HIP, R_HIP):
                continue
            P[k] = hip_c + trunk[i] @ (P[k] - hip_c)
        for k, v in P.items():
            pts_body[i, k] = v
    # body (X anterior, Y up, Z right) -> world (Y up) facing a level camera rotated by yaw
    yaw = _ry(np.radians(p["yaw"]))
    world = pts_body @ yaw.T
    cam = np.stack([-world[..., 2], -world[..., 1], p["dist"] - world[..., 0]], axis=-1)
    cam += rng.normal(0, 0.006, cam.shape)
    acc, gyro = _virtual_wrist_imu(world, side, rng)
    correct = None if exercise == "unknown" else comp is None
    comp_vec = np.full(len(COMP_FLAGS), -1 if exercise == "unknown" else 0)
    comp_vec[COMP_FLAGS.index("SHORT_ROM")] = -1
    if comp:
        comp_vec[COMP_FLAGS.index(comp)] = 1
    seq = SkeletonSequence(subject=subject, exercise=exercise, side=side, points=cam, fps=FPS, source="synthetic",
                           name=f"{exercise}_{comp or 'ok'}_{kind}", correct=correct,
                           meta={"phase": phase, "comp": comp_vec, "kind": kind})
    return seq, acc, gyro


def _virtual_wrist_imu(world: np.ndarray, side: str, rng) -> tuple:
    el, wr = (R_ELBOW, R_WRIST) if side == "right" else (L_ELBOW, L_WRIST)
    sh = R_SHOULDER if side == "right" else L_SHOULDER
    p = world[:, wr]
    x = world[:, wr] - world[:, el]
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    up = world[:, sh] - world[:, el]
    z = np.cross(x, up)
    bad = np.linalg.norm(z, axis=1) < 1e-3
    z[bad] = np.cross(x[bad], [1.0, 0, 0])
    z /= np.linalg.norm(z, axis=1, keepdims=True)
    y = np.cross(z, x)
    R = np.stack([x, y, z], axis=2)                       # world <- sensor (columns)
    dt = 1.0 / FPS
    acc_w = np.gradient(np.gradient(p, dt, axis=0), dt, axis=0) + np.array([0, G, 0])
    acc = np.einsum("nji,nj->ni", R, acc_w)
    dR = np.gradient(R, dt, axis=0)
    W = np.einsum("nji,njk->nik", R, dR)
    gyro = np.degrees(np.stack([W[:, 2, 1], W[:, 0, 2], W[:, 1, 0]], axis=1))
    return acc + rng.normal(0, 0.15, acc.shape), gyro + rng.normal(0, 1.5, gyro.shape)


def synthetic_people(n_subjects: int = 6, seqs_per_class: int = 3, seed: int = 0, with_comp: bool = True) -> list:
    """-> list of (SkeletonSequence, acc, gyro) for every class, subject, both sides."""
    rng = np.random.default_rng(seed)
    out = []
    for s in range(n_subjects):
        p = subject_params(rng)
        side = "right" if s % 2 == 0 else "left"
        for ex in CLASSES:
            for k in range(seqs_per_class):
                comp = None
                if with_comp and ex in COMPS and k == seqs_per_class - 1:
                    comp = COMPS[ex][int(rng.integers(len(COMPS[ex])))]
                out.append(make_sequence(ex, side, rng, p, comp=comp, subject=f"SYN{s:02d}"))
    return out
