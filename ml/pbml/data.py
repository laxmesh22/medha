"""Segment data model + on-disk format + a synthetic generator for pipeline testing.

On-disk format (what the team records):
    <root>/<subject_id>/<exercise_id>/<segment_name>.csv
    columns: t_ms, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z   (wrist/forearm IMU, sensor frame)
    acc in m/s^2 (specific force, includes gravity), gyro in deg/s, ~100 Hz.
One CSV = one exercise segment (rest trimmed), as in Lee 2024.

The synthetic generator is ONLY for testing code paths and showing the random-split vs LOSO gap.
Its accuracy numbers say nothing about real performance.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .exercises import CLASS_IDS

FS = 100.0
G = 9.81


@dataclass
class Segment:
    subject: str
    exercise: str
    acc: np.ndarray   # (T, 3) m/s^2
    gyro: np.ndarray  # (T, 3) deg/s
    name: str = ""
    side: str = "right"  # arm wearing the sensor


# ---------------------------------------------------------------------------- disk I/O
def save_segment(root: Path, seg: Segment) -> Path:
    path = Path(root) / seg.subject / seg.exercise / f"{seg.name or 'seg'}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(len(seg.acc)) * (1000.0 / FS)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_ms", "acc_x", "acc_y", "acc_z", "gyro_x", "gyro_y", "gyro_z"])
        for i in range(len(t)):
            w.writerow([f"{t[i]:.1f}", *(f"{v:.5f}" for v in seg.acc[i]), *(f"{v:.4f}" for v in seg.gyro[i])])
    return path


def load_dataset(root: Path) -> list:
    segs = []
    for f in sorted(Path(root).glob("*/*/*.csv")):
        a = np.loadtxt(f, delimiter=",", skiprows=1, ndmin=2)
        segs.append(Segment(subject=f.parent.parent.name, exercise=f.parent.name,
                            acc=a[:, 1:4], gyro=a[:, 4:7], name=f.stem))
    return segs


# ---------------------------------------------------------------------------- synthetic
def _rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _bump(n, reps):
    """Smooth 0->1->0 repetitions over n samples."""
    t = np.linspace(0, reps, n)
    return 0.5 - 0.5 * np.cos(2 * np.pi * t)


def _trajectory(ex: str, n: int, rng, amp: float):
    """Joint angles (rad) over time for one exercise: trunk pitch/roll, shoulder flex/abd/rot, elbow."""
    z = np.zeros(n)
    b = _bump(n, reps=rng.uniform(2.5, 4.0))
    d = np.radians
    trunk_pitch, trunk_roll, flex, abd, rot, elbow = z.copy(), z.copy(), z.copy(), z.copy(), z.copy(), z.copy()
    t = np.linspace(0, 1, n)
    if ex == "pendulum":
        trunk_pitch += d(60)
        ph = 2 * np.pi * rng.uniform(4, 6) * t
        flex, abd = d(15) * amp * np.sin(ph), d(15) * amp * np.cos(ph)
    elif ex == "posterior_capsule_stretch":
        flex += d(90)
        abd = -d(35) * amp * b                      # horizontal adduction across the body
        elbow += d(20)
    elif ex == "pec_minor_stretch":
        abd += d(90); rot += d(80); elbow += d(90)
        trunk_pitch = d(10) * b
    elif ex == "lawnmower":
        trunk_pitch += d(30)
        flex = d(-20) + d(80) * amp * b
        abd = d(-30) + d(60) * amp * b
        elbow = d(90) * (1 - b)
        trunk_roll = d(15) * b
    elif ex == "abduction_band":
        abd = d(85) * amp * b
    elif ex == "extension_band":
        flex = -d(40) * amp * b
        elbow += d(10)
    elif ex == "er_band":
        elbow += d(90); rot = d(45) * amp * b
    elif ex == "ir_band":
        elbow += d(90); rot = d(30) - d(70) * amp * b
    elif ex == "er_sidelying":
        trunk_roll += d(90); elbow += d(90); rot = d(-30) + d(70) * amp * b
    elif ex == "prone_extension":
        trunk_pitch += d(90); flex = d(90) - d(60) * amp * b
    elif ex == "anterior_deltoid":
        flex = d(90) * amp * b
    else:
        raise ValueError(ex)
    return trunk_pitch, trunk_roll, flex, abd, rot, elbow


def simulate_segment(ex: str, subject_params: dict, rng, seconds: float = 12.0) -> Segment:
    """Virtual wrist IMU: forward kinematics -> specific force + angular velocity in the sensor frame."""
    n = int(seconds * FS * subject_params["speed"])
    angles = _trajectory(ex, n, rng, subject_params["amp"])
    L1, L2 = subject_params["upper_arm"], subject_params["forearm"]
    mount = subject_params["mount"]
    R = np.empty((n, 3, 3))
    p = np.empty((n, 3))
    for i in range(n):
        tp, tr, fl, ab, ro, el = (a[i] for a in angles)
        R_trunk = _rz(tp) @ _rx(tr)                     # world <- trunk (Y up, X anterior, Z right)
        R_sh = _rz(fl) @ _rx(ab) @ _ry(ro)              # trunk <- humerus
        R_el = _rz(el)                                  # humerus <- forearm
        R_fore = R_trunk @ R_sh @ R_el
        p[i] = R_trunk @ (R_sh @ np.array([0, -L1, 0]) + R_sh @ R_el @ np.array([0, -L2, 0]))
        R[i] = R_fore @ mount                           # world <- sensor
    dt = 1.0 / FS
    vel = np.gradient(p, dt, axis=0)
    acc_w = np.gradient(vel, dt, axis=0) + np.array([0, G, 0])  # specific force
    acc = np.einsum("nji,nj->ni", R, acc_w)                      # R^T a
    dR = np.gradient(R, dt, axis=0)
    W = np.einsum("nji,njk->nik", R, dR)                         # R^T dR = [w]x (body frame)
    gyro = np.degrees(np.stack([W[:, 2, 1], W[:, 0, 2], W[:, 1, 0]], axis=1))
    acc += rng.normal(0, 0.15, acc.shape)
    gyro += rng.normal(0, 1.5, gyro.shape) + subject_params["gyro_bias"]
    return Segment(subject="", exercise=ex, acc=acc, gyro=gyro)


def synthetic_dataset(n_subjects: int = 10, reps_per_exercise: int = 6, seed: int = 0,
                      exercises=CLASS_IDS) -> list:
    """Each simulated subject has their own anatomy, speed, ROM and strap mounting, which is what makes
    random-split accuracy look better than LOSO."""
    rng = np.random.default_rng(seed)
    segs = []
    for s in range(n_subjects):
        mount_angles = rng.normal(0, np.radians(15), 3)
        params = {
            "upper_arm": rng.uniform(0.26, 0.34),
            "forearm": rng.uniform(0.22, 0.29),
            "speed": rng.uniform(0.7, 1.3),
            "amp": rng.uniform(0.55, 1.0),               # restricted ROM in some "patients"
            "mount": _rx(mount_angles[0]) @ _ry(mount_angles[1]) @ _rz(mount_angles[2]),
            "gyro_bias": rng.normal(0, 1.0, 3),
        }
        for ex in exercises:
            for r in range(reps_per_exercise):
                seg = simulate_segment(ex, params, rng)
                seg.subject, seg.name = f"S{s:02d}", f"{ex}_{r:02d}"
                segs.append(seg)
    return segs
