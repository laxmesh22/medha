"""Which joints the camera overlay may draw.

Show a joint at visibility >= 0.6. Once shown, keep it until visibility falls below
0.35, or it is missing for a few frames. Then fade the last on-screen position for
at most 150 ms. A joint outside the picture is not drawn. This never feeds the
angle calculation: a missing measurement stays unavailable.
"""

from __future__ import annotations

import math

SHOW = 0.6
HIDE = 0.35
HOLD_MS = 150.0
MISS_N = 6
# A joint just past the border is still that joint. Drawn clamped to the frame.
# Farther than this is an extrapolation (hips below a close-up) and is not drawn.
_EDGE = 0.12
CLOSE_HINT = "Step back 1-2 m: shoulders, elbows and hips must be in view"
# Shoulder span this wide means the person is filling the frame.
_CLOSE_SPAN = 0.42
_L_SHOULDER, _R_SHOULDER = 5, 6
_L_HIP, _R_HIP = 11, 12


def _coords(point):
    if not point or len(point) < 2 or point[0] is None or point[1] is None:
        return None
    u, v = float(point[0]), float(point[1])
    if not (math.isfinite(u) and math.isfinite(v)):
        return None
    return u, v


def _near_frame(point) -> bool:
    got = _coords(point)
    if got is None:
        return False
    u, v = got
    return -_EDGE <= u <= 1.0 + _EDGE and -_EDGE <= v <= 1.0 + _EDGE


def _inside(point) -> bool:
    """On the picture itself. The step-back hint uses this, not the draw margin."""
    got = _coords(point)
    if got is None:
        return False
    u, v = got
    return 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0


class _Joint:
    def __init__(self):
        self.on = False
        self.u = None
        self.v = None
        self.t = None
        self.miss = 0


class LandmarkGate:
    def __init__(self):
        self._joints = [_Joint() for _ in range(17)]

    def update(self, kp2d, scores, t_ms: float):
        """One entry per joint: ``None``, or ``[u, v, alpha]``. Never a fake 0."""
        out = []
        for i, joint in enumerate(self._joints):
            point = None if not kp2d or i >= len(kp2d) else kp2d[i]
            score = None if not scores or i >= len(scores) or scores[i] is None else float(scores[i])
            out.append(self._step(joint, point, score, t_ms))
        return out

    def _step(self, joint: _Joint, point, score, t_ms: float):
        near = _near_frame(point)
        keep = near and score is not None and math.isfinite(score) and score >= (HIDE if joint.on else SHOW)
        if joint.on and keep:
            u, v = _coords(point)
            joint.u, joint.v = min(1.0, max(0.0, u)), min(1.0, max(0.0, v))
            joint.t = t_ms
            joint.miss = 0
            return [round(joint.u, 4), round(joint.v, 4), 1.0]
        if joint.on:
            joint.miss += 1
            age = HOLD_MS + 1 if joint.t is None else t_ms - joint.t
            if joint.u is not None and age <= HOLD_MS and joint.miss <= MISS_N:
                alpha = max(0.0, 1.0 - age / HOLD_MS)
                return [round(joint.u, 4), round(joint.v, 4), round(alpha, 3)]
            joint.on = False
            joint.u = joint.v = joint.t = None
            joint.miss = 0
            return None
        if near and score is not None and math.isfinite(score) and score >= SHOW:
            joint.on = True
            u, v = _coords(point)
            joint.u, joint.v = min(1.0, max(0.0, u)), min(1.0, max(0.0, v))
            joint.t = t_ms
            joint.miss = 0
            return [round(joint.u, 4), round(joint.v, 4), 1.0]
        return None


def close_hint(kp2d, scores) -> str | None:
    """The step-back line when the shoulders fill the frame or the hips are out of it."""
    if not kp2d or not scores or len(kp2d) < 13 or len(scores) < 13:
        return None

    def on_screen(i) -> bool:
        return _inside(kp2d[i]) and scores[i] is not None and float(scores[i]) >= HIDE

    if not (on_screen(_L_SHOULDER) or on_screen(_R_SHOULDER)):
        return None
    span = None
    left, right = kp2d[_L_SHOULDER], kp2d[_R_SHOULDER]
    if left and right and left[0] is not None and right[0] is not None:
        span = abs(float(left[0]) - float(right[0]))
    hips = on_screen(_L_HIP) and on_screen(_R_HIP)
    if (span is not None and span >= _CLOSE_SPAN) or not hips:
        return CLOSE_HINT
    return None
