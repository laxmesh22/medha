"""Count down, then call the station's real strap calibration endpoints.

The straps must already be connected on the hub (port 8012). Put them on first:
upper arm, forearm, and waist, lid facing out. Stand about 2 m from the camera.

    hub/.venv/Scripts/python.exe tools/calibrate_straps.py
"""
from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8012"
LABEL = {"none": "not calibrated", "npose": "N-pose ok", "raise": "raise ok"}
ANGLE_NEEDS = {
    "elevation": "upper arm and trunk",
    "apparent_elevation": "upper arm",
    "elbow_flexion": "forearm",
    "rotation": "forearm",
    "trunk_lean_sagittal": "trunk",
    "trunk_lean_lateral": "trunk",
}


def countdown(line: str) -> None:
    for left in range(5, 0, -1):
        print(f"{line}  {left}", flush=True)
        time.sleep(1)


def post(path: str) -> dict:
    req = urllib.request.Request(BASE + path, method="POST")
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.load(resp)


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return json.load(resp)


def _table(title: str, body: dict, view: dict) -> None:
    print(f"\n{title}: {'accepted' if body.get('ok') else 'rejected'}", flush=True)
    if body.get("reason"):
        print(f"  reason: {body['reason']}")
    sensors = body.get("sensors") or {}
    for name, row in sensors.items():
        print(f"  {name}: samples {row.get('samples')}  gyro peak {row.get('gyro_peak_rad_s')} rad/s")
    if body.get("refined") is not None:
        print(f"  refined: {', '.join(body.get('refined') or []) or 'none'}")
    for slot in view.get("slots") or []:
        state = LABEL.get(slot.get("state"), slot.get("state"))
        offset = slot.get("offset_deg")
        offset_s = "unavailable" if offset is None else f"{offset} deg"
        print(f"  {slot.get('sensor')}: {state}  gravity offset {offset_s}")


def _angles() -> None:
    try:
        import asyncio
        import websockets
    except ImportError:
        print("angles: websockets is not installed, so the live row was skipped")
        return

    async def one():
        async with websockets.connect("ws://127.0.0.1:8012/ws/live", max_size=2**22) as ws:
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

    state = asyncio.run(one())
    angles = ((state.get("straps") or {}).get("angles")) or {}
    print("\nStrap angles after calibration:")
    if not angles:
        print("  none yet (a missing angle stays unavailable, not 0)")
        return
    for key, needs in ANGLE_NEEDS.items():
        item = angles.get(key) or {}
        if item.get("value") is None:
            why = item.get("reason") or f"needs {needs}"
            print(f"  {key}: unavailable ({why})")
        else:
            print(f"  {key}: {item['value']} deg")


def main() -> int:
    print("Put each strap on: upper arm, forearm, waist. Lid facing out.")
    print("Arrow along the limb; the waist arrow points up.")
    print("Stand about 2 m from the camera, where the shoulders, elbows and hips are in view.")
    print("This uses the station on port 8012. Stand still when the count finishes, then raise.")
    countdown("Stand still, arms by your sides, palms on your thighs. N-pose starts in")
    print("Hold still…", flush=True)
    npose = post("/api/straps/calibrate/npose")
    view = get("/api/straps/calibration")
    _table("N-pose", npose, view)
    if not npose.get("ok"):
        print("\nN-pose was not accepted, so the raise was not started.")
        return 1
    countdown("One slow straight-arm forward raise starts in")
    print("Raise the straight arm slowly forward…", flush=True)
    raise_body = post("/api/straps/calibrate/raise")
    view = get("/api/straps/calibration")
    _table("Forward raise", raise_body, view)
    _angles()
    return 0 if raise_body.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
