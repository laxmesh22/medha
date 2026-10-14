"""Plausibility checks on the 3D skeleton (design doc §6.2 step 4)."""

from __future__ import annotations

from collections import deque

import numpy as np

from ..datatypes import (
    L_ELBOW, L_SHOULDER, L_WRIST, R_ELBOW, R_SHOULDER, R_WRIST, Skeleton3D,
)

# Absolute sanity ranges in metres (keypoint-to-keypoint, not bone lengths).
RANGES = {
    "shoulder_width": (0.22, 0.60),
    "upper_arm": (0.16, 0.45),
    "forearm": (0.14, 0.40),
}


class SegmentTracker:
    """Tracks per-session median segment lengths; flags frames that deviate too much.

    A sudden change in apparent upper-arm length almost always means a bad depth sample
    (keypoint landed on background) or a left/right swap - not a real change in anatomy.
    """

    def __init__(self, side: str = "right", window: int = 90, max_rel_dev: float = 0.15,
                 min_history: int = 15):
        s, e, w = (R_SHOULDER, R_ELBOW, R_WRIST) if side == "right" else (L_SHOULDER, L_ELBOW, L_WRIST)
        self.pairs = {
            "shoulder_width": (L_SHOULDER, R_SHOULDER),
            "upper_arm": (s, e),
            "forearm": (e, w),
        }
        self.max_rel_dev = max_rel_dev
        self.min_history = min_history
        self.hist = {k: deque(maxlen=window) for k in self.pairs}

    def check(self, sk: Skeleton3D) -> list:
        """Return a list of flags like ``IMPLAUSIBLE_UPPER_ARM``. Updates history with good frames."""
        flags = []
        for name, (a, b) in self.pairs.items():
            if not (sk.valid[a] and sk.valid[b]):
                continue
            length = float(np.linalg.norm(sk.points[a] - sk.points[b]))
            lo, hi = RANGES[name]
            if not lo <= length <= hi:
                flags.append(f"IMPLAUSIBLE_{name.upper()}")
                continue
            h = self.hist[name]
            if len(h) >= self.min_history:
                med = float(np.median(h))
                if abs(length - med) / med > self.max_rel_dev:
                    flags.append(f"IMPLAUSIBLE_{name.upper()}")
                    continue
            h.append(length)
        return flags

    def medians(self) -> dict:
        return {k: (float(np.median(h)) if h else None) for k, h in self.hist.items()}
