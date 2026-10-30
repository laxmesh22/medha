"""Accuracy check for the straps without a camera: hold known poses, compare against what they should be.

Run while doing, in order, and holding each still for about 4 s:
    1 arms hanging down      expect upper 0 deg, elbow 0 deg
    2 forward raise, level   expect upper 90 deg, heading 0 (toward the camera)
    3 side raise, level      expect upper 90 deg, heading -90 (patient's right; +90 for a left arm)
    4 arm down, elbow 90     expect upper 0 deg, elbow 90 deg, forearm pointing forward

    hub/.venv/Scripts/python.exe tools/strap_pose_test.py --seconds 45

Elevation is from gravity and needs no camera. Heading is relative to the forward set by the calibration raise.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time

import numpy as np
import websockets

STILL_DPS = 15.0
MIN_HOLD_S = 1.5


def unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return None if n < 1e-6 else v / n


def deg(a, b) -> float:
    return math.degrees(math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0))))


def heading(v):
    return None if math.hypot(v[0], v[2]) < 0.4 else math.degrees(math.atan2(v[0], v[2]))


async def collect(url: str, seconds: float) -> list:
    rows = []
    async with websockets.connect(url, max_size=None) as ws:
        t0 = time.time()
        while time.time() - t0 < seconds:
            s = json.loads(await ws.recv())
            pose = s.get("strap_pose") or {}
            u, f = pose.get("upper_arm"), pose.get("forearm")
            if not u or not f:
                continue
            speed = max((d.get("gyro_dps") or 0.0) for d in (s.get("straps") or {}).get("devices", []))
            rows.append((time.time() - t0, unit(u), unit(f), speed))
    return rows


def holds(rows: list) -> list:
    out, cur = [], []
    for row in rows + [(None, None, None, 1e9)]:
        if row[3] < STILL_DPS:
            cur.append(row)
            continue
        if cur and cur[-1][0] - cur[0][0] >= MIN_HOLD_S:
            out.append(cur)
        cur = []
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--url", default="ws://127.0.0.1:8012/ws/live")
    args = ap.parse_args()
    rows = asyncio.run(collect(args.url, args.seconds))
    if not rows:
        print("No strap pose. Are both arm bands connected and calibrated?")
        return
    down = np.array([0.0, -1.0, 0.0])
    print(f"{len(rows)} frames; still holds of {MIN_HOLD_S}s or more:")
    for i, h in enumerate(holds(rows), 1):
        u = unit(np.mean([r[1] for r in h], axis=0))
        f = unit(np.mean([r[2] for r in h], axis=0))
        hu, hf = heading(u), heading(f)
        print(f" {i}. {h[0][0]:5.1f}-{h[-1][0]:5.1f}s  upper elevation {deg(u, down):5.1f}"
              f"  heading {'-' if hu is None else f'{hu:+6.1f}'}"
              f" | forearm elevation {deg(f, down):5.1f} heading {'-' if hf is None else f'{hf:+6.1f}'}"
              f" | elbow {deg(u, f):5.1f}")


if __name__ == "__main__":
    main()
