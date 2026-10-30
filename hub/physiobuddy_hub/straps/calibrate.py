"""N-pose and forward-raise capture for the strap angles. Degrees stay in strap_kin."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

import numpy as np

from ..core.strap_kin import SENSORS, StrapCalibration, StrapKinematics

STILL_GYRO_RAD_S = 0.3
MIN_NPOSES = 20
# The position the sensors were worn in. Git-ignored. Replaced only by a new calibration.
MOUNT_FILE = Path(__file__).resolve().parents[2] / "straps_mount.local.json"


def judge_npose(samples: dict) -> dict:
    """``samples``: sensor -> list of (quaternion, gyro rad/s or None).

    A sensor with no rows is not on this pod. One with enough samples must be still.
    A short one is left out; it must not reject the arms.
    """
    present = {s: rows for s, rows in samples.items() if s in SENSORS and rows}
    detail = {}
    if not present:
        return {"ok": False, "reason": "no strap samples", "sensors": detail}
    short = []
    moving = []
    usable = {}
    for name, rows in present.items():
        peak = None
        for _quat, gyro in rows:
            if gyro is None:
                continue
            mag = float(np.linalg.norm(np.asarray(gyro, float)))
            peak = mag if peak is None else max(peak, mag)
        detail[name] = {"samples": len(rows), "gyro_peak_rad_s": None if peak is None else round(peak, 3)}
        if len(rows) < MIN_NPOSES:
            short.append(name)
            continue
        if peak is not None and peak > STILL_GYRO_RAD_S:
            moving.append(name)
            continue
        usable[name] = rows
    if moving:
        return {"ok": False, "reason": f"moving ({', '.join(moving)} over {STILL_GYRO_RAD_S} rad/s)",
                "sensors": detail}
    if not usable:
        return {"ok": False, "reason": f"fewer than {MIN_NPOSES} samples ({', '.join(short)})", "sensors": detail}
    return {"ok": True, "quats": {s: [q for q, _g in rows] for s, rows in usable.items()}, "sensors": detail}


def save_worn_mount(cal: StrapCalibration, when: str) -> None:
    """Lock the orientation the sensors had when they were worn and calibrated."""
    payload = {"time": when, **cal.to_dict()}
    MOUNT_FILE.write_text(json.dumps(payload), encoding="utf-8")


def load_worn_mount(side: str) -> Optional[tuple]:
    """Return ``(calibration, time)`` when a saved mount exists for this side."""
    if not MOUNT_FILE.is_file():
        return None
    try:
        data = json.loads(MOUNT_FILE.read_text(encoding="utf-8"))
        cal = StrapCalibration.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if cal.side != side or not cal.ref:
        return None
    return cal, data.get("time")


def strap_frame(cal: Optional[StrapCalibration], snap: dict):
    """Calibrated snapshot -> (angles dict or None, imu block or None). Gyro in the block is deg/s."""
    if cal is None:
        return None, None
    quats = {}
    for name, view in snap.items():
        if name not in SENSORS or not view or not view.get("available") or view.get("quat") is None:
            continue
        quats[name] = view["quat"]
    if not quats:
        return None, None
    angles = StrapKinematics(cal).compute(quats).to_dict()
    gyro, up = {}, {}
    for name, quat in quats.items():
        view = snap.get(name) or {}
        g = cal.gyro_in_segment(name, view.get("gyro"))
        if g is not None:
            gyro[name] = np.degrees(np.asarray(g, float))
        u = cal.up_in_segment(name, quat)
        if u is not None:
            up[name] = np.asarray(u, float)
    return angles, {"angles": angles, "gyro": gyro, "up": up}


def strap_pose(cal: Optional[StrapCalibration], snap: dict):
    """Limb directions for the 3D figure, in the display frame (y up, z toward the camera).

    None for a limb whose strap is missing. Never a zero vector.
    """
    if cal is None or not snap:
        return None
    quats = {}
    for name, view in snap.items():
        if name not in SENSORS or not view or not view.get("available") or view.get("quat") is None:
            continue
        quats[name] = view["quat"]
    if not quats:
        return None
    down = np.array([0.0, -1.0, 0.0])
    up = np.array([0.0, 1.0, 0.0])
    Qt = cal.segment("trunk", quats.get("trunk"))
    Qa = cal.segment("upper_arm", quats.get("upper_arm"))
    Qf = cal.segment("forearm", quats.get("forearm"))

    def show(vec) -> Optional[list]:
        v = np.asarray(vec, float)
        n = float(np.linalg.norm(v))
        if n < 1e-6 or not np.all(np.isfinite(v)):
            return None
        v = v / n
        return [round(float(-v[2]), 4), round(float(v[1]), 4), round(float(v[0]), 4)]

    pose = {"side": cal.side, "trunk": None, "upper_arm": None, "forearm": None}
    # A missing waist sample keeps the calibrated stand. Clinical angles stay unavailable;
    # the figure does not invent a lean, and the arms still have a body frame.
    trunk_q = Qt if Qt is not None else np.eye(3)
    if Qt is not None:
        pose["trunk"] = show(trunk_q @ up)
    if Qa is not None:
        pose["upper_arm"] = show(trunk_q.T @ Qa @ down)
    if Qf is not None:
        pose["forearm"] = show(trunk_q.T @ Qf @ down)
    if pose["trunk"] is None and pose["upper_arm"] is None and pose["forearm"] is None:
        return None
    return pose


def _keep(buckets, seen, name, quat, gyro, seq) -> None:
    if name not in buckets or quat is None:
        return
    if seq is not None:
        key = (name, seq)
        if key in seen:
            return
        seen.add(key)
    buckets[name].append((quat, gyro))


async def collect_samples(link, seconds: float) -> dict:
    """Unique samples (by seq) over ``seconds``. Does not block the camera thread.

    The link keeps every packet, not only the latest. A poll of the snapshot misses
    packets that arrived in the same burst, which is what happens while the webcam runs.
    """
    buckets = {name: [] for name in SENSORS}
    seen = set()
    drain = getattr(link, "drain_new", None)
    if drain is not None and hasattr(link, "discard_pending"):
        link.discard_pending()
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        if drain is not None:
            for name, rows in drain().items():
                for quat, gyro, seq in rows:
                    _keep(buckets, seen, name, quat, gyro, seq)
        else:
            snap = link.snapshot()
            for name, view in snap.items():
                if not view or not view.get("available"):
                    continue
                _keep(buckets, seen, name, view.get("quat"), view.get("gyro"), view.get("seq"))
        await asyncio.sleep(0.01)
    return buckets
