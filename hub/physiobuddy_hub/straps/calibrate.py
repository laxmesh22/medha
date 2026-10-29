"""N-pose and forward-raise capture for the strap angles. Degrees stay in strap_kin."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import numpy as np

from ..core.strap_kin import SENSORS, StrapCalibration, StrapKinematics

STILL_GYRO_RAD_S = 0.3
MIN_NPOSES = 50


def judge_npose(samples: dict) -> dict:
    """``samples``: sensor -> list of (quaternion, gyro rad/s or None).

    A sensor with no rows is not on this pod. One that showed up must be still and have enough samples.
    """
    present = {s: rows for s, rows in samples.items() if s in SENSORS and rows}
    detail = {}
    if not present:
        return {"ok": False, "reason": "no strap samples", "sensors": detail}
    short = []
    moving = []
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
        elif peak is not None and peak > STILL_GYRO_RAD_S:
            moving.append(name)
    if short:
        return {"ok": False, "reason": f"fewer than {MIN_NPOSES} samples ({', '.join(short)})", "sensors": detail}
    if moving:
        return {"ok": False, "reason": f"moving ({', '.join(moving)} over {STILL_GYRO_RAD_S} rad/s)",
                "sensors": detail}
    return {"ok": True, "quats": {s: [q for q, _g in rows] for s, rows in present.items()}, "sensors": detail}


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


async def collect_samples(link, seconds: float) -> dict:
    """Unique samples (by seq) over ``seconds``. Does not block the camera thread."""
    buckets = {name: [] for name in SENSORS}
    seen = set()
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        snap = link.snapshot()
        for name, view in snap.items():
            if name not in buckets or not view or not view.get("available") or view.get("quat") is None:
                continue
            seq = view.get("seq")
            if seq is not None:
                key = (name, seq)
                if key in seen:
                    continue
                seen.add(key)
            buckets[name].append((view["quat"], view.get("gyro")))
        await asyncio.sleep(0.01)
    return buckets
