"""Which angles the coach judges: camera, straps, or neither (handoff §9.4 fusion table).

* Camera and straps both measure the metric: the camera stays the measurement and the straps are the check. If they
  disagree by more than ``DISAGREE_DEG`` the frame is marked low quality (not counted) and the coach asks to repeat.
  The two are never averaged.
* Only the straps measure it: the straps are used only when the station enables ``strap_coach``. Strap-only counting
  is not validated yet, so it is an explicit operator choice, off by default.
* Straps add what the camera judges poorly: a bent elbow during a straight-arm raise, and trunk lean from the waist.

Degrees come from geometry only (camera skeleton or strap quaternions). Missing stays unavailable.
"""
from __future__ import annotations

import copy
from typing import Optional

DISAGREE_DEG = 20.0
ELBOW_BENT_DEG = 25.0        # straight-arm raises: elbow bend above this is a fault
RAISED_FOR_ELBOW_DEG = 30.0  # only judge the elbow once the arm is clearly raised
STRAIGHT_ARM = ("flexion", "abduction")
TRUNK_FLAGS = ("TRUNK_LEAN_SAGITTAL", "TRUNK_LEAN_LATERAL")


def _value(angles: Optional[dict], key: str) -> Optional[float]:
    m = (angles or {}).get(key) or {}
    v = m.get("value")
    return None if v is None or m.get("quality") == "low" else float(v)


def fuse(camera: Optional[dict], straps: Optional[dict], exercise_id: str, metric: str,
         strap_coach: bool) -> tuple:
    """Returns ``(angles for the coach, info)``. ``info``: source, disagree_deg, strap_flags."""
    cam_v, strap_v = _value(camera, metric), _value(straps, metric)
    info = {"source": None, "disagree_deg": None, "strap_flags": []}
    if cam_v is not None:
        out, info["source"] = copy.deepcopy(camera), "camera"
    elif strap_v is not None and strap_coach:
        out, info["source"] = copy.deepcopy(straps), "straps"
        out[metric]["reason"] = "measured by the bands"
    else:
        return camera, info

    if straps:
        extra = []
        elbow = _value(straps, "elbow_flexion")
        level = _value(straps, "elevation") if _value(straps, "elevation") is not None else _value(out, "elevation")
        if (exercise_id in STRAIGHT_ARM and elbow is not None and elbow > ELBOW_BENT_DEG
                and level is not None and level > RAISED_FOR_ELBOW_DEG):
            extra.append("ELBOW_BENT")
        # The waist strap measures the trunk directly; the camera's trunk estimate is the weaker one.
        extra += [f for f in (straps.get("flags") or []) if f in TRUNK_FLAGS]
        flags = list(out.get("flags") or [])
        for f in extra:
            if f not in flags:
                flags.append(f)
        out["flags"] = flags
        info["strap_flags"] = extra

    if info["source"] == "camera" and strap_v is not None:
        gap = abs(cam_v - strap_v)
        info["disagree_deg"] = round(gap, 1)
        if gap > DISAGREE_DEG:
            out[metric]["quality"] = "low"
            out[metric]["reason"] = f"camera and bands disagree by {gap:.0f}°, please repeat slowly"
    return out, info
