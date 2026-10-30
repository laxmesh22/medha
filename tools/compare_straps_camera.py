"""Compare the strap-driven limb directions with the camera skeleton, live.

Run while the patient stands in the camera view with the straps calibrated:
    hub/.venv/Scripts/python.exe tools/compare_straps_camera.py --seconds 30

Both come from the station's /ws/live state in the same display frame (x patient's left, y up, z toward the camera).
The webcam's depth is weak, so elevation (angle from straight down) is the most trustworthy comparison; heading
(direction around the body) shows a forward-reference error, and a growing error over time shows drift.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time

import numpy as np
import websockets

# COCO indices: shoulder, elbow, wrist
JOINTS = {"right": (6, 8, 10), "left": (5, 7, 9)}


def unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return None if n < 1e-6 or not np.all(np.isfinite(v)) else v / n


def angle(a, b) -> float:
    return math.degrees(math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0))))


def elevation(v) -> float:
    return angle(v, np.array([0.0, -1.0, 0.0]))


def heading(v):
    """Direction around the body in degrees (0 toward the camera, +90 patient's left); None near vertical."""
    flat = math.hypot(v[0], v[2])
    return None if flat < 0.4 else math.degrees(math.atan2(v[0], v[2]))


def wrap(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


async def collect(url: str, seconds: float) -> list:
    rows = []
    async with websockets.connect(url, max_size=None) as ws:
        t0 = time.time()
        while time.time() - t0 < seconds:
            s = json.loads(await ws.recv())
            pose, kp = s.get("strap_pose"), s.get("keypoints")
            if not pose or not kp:
                continue
            sh, el, wr = JOINTS.get(pose.get("side") or "right", JOINTS["right"])
            cam = {}
            if kp[sh] and kp[el]:
                cam["upper_arm"] = unit(np.subtract(kp[el], kp[sh]))
            if kp[el] and kp[wr]:
                cam["forearm"] = unit(np.subtract(kp[wr], kp[el]))
            for seg, cv in cam.items():
                sv = unit(pose[seg]) if pose.get(seg) else None
                if cv is not None and sv is not None:
                    rows.append((time.time() - t0, seg, cv, sv))
    return rows


def report(rows: list) -> None:
    if not rows:
        print("No frames with both a camera skeleton and a strap pose. Stand in view with the straps calibrated.")
        return
    for seg in ("upper_arm", "forearm"):
        r = [x for x in rows if x[1] == seg]
        if not r:
            print(f"{seg}: no paired frames")
            continue
        full = [angle(c, s) for _t, _s, c, s in r]
        elev = [elevation(s) - elevation(c) for _t, _s, c, s in r]
        heads = [wrap(heading(s) - heading(c)) for _t, _s, c, s in r if heading(s) is not None and heading(c) is not None]
        mirror = [angle(c * np.array([-1, 1, 1]), s) for _t, _s, c, s in r]
        flip = [angle(c * np.array([1, 1, -1]), s) for _t, _s, c, s in r]
        half = len(r) // 2
        print(f"{seg}: {len(r)} frames")
        print(f"  3D angle error   median {np.median(full):5.1f} deg  (first half {np.median(full[:half] or full):5.1f},"
              f" second half {np.median(full[half:]):5.1f})")
        print(f"  elevation error  median {np.median(elev):+5.1f} deg  (strap minus camera)")
        if heads:
            print(f"  heading offset   median {np.median(heads):+6.1f} deg over {len(heads)} raised frames"
                  " (constant = forward reference off; ~180 = front/back reversed)")
        print(f"  if left/right were mirrored: {np.median(mirror):5.1f} deg; if front/back flipped: {np.median(flip):5.1f} deg")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--url", default="ws://127.0.0.1:8012/ws/live")
    args = ap.parse_args()
    report(asyncio.run(collect(args.url, args.seconds)))


if __name__ == "__main__":
    main()
