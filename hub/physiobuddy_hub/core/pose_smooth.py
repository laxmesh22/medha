"""Display-only follow for the on-screen skeleton.

The coach and the angle readouts keep the measured pose. A missing joint stays
missing: the filter never writes 0, and a gap reseeds instead of bridging it.

``light`` (the default) is a fast One-Euro plus a short lead, so the drawn arm
keeps up with the camera picture. ``normal`` is a slower follow. ``off`` is the
measured pose with no follow.
"""

from __future__ import annotations

import math

MODES = ("off", "light", "normal")

# min cutoff Hz, speed gain, lead seconds, max lead per coordinate
_LIGHT = (6.0, 0.4, 0.030, None)
_NORMAL = (2.0, 0.05, 0.0, None)
# 3D joints are metres about the shoulders. 2D joints are fractions of the frame.
_CAP_3D = 0.08
_CAP_2D = 0.05


def _alpha(dt: float, cutoff: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class _Channel:
    def __init__(self, min_cutoff: float, beta: float, lead_s: float, cap: float):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.lead_s = lead_s
        self.cap = cap
        self.x: float | None = None
        self.dx = 0.0
        self.t: float | None = None

    def reset(self) -> None:
        self.x = None
        self.dx = 0.0
        self.t = None

    def update(self, value, t_ms: float):
        if value is None:
            self.reset()
            return None
        number = float(value)
        if not math.isfinite(number):
            self.reset()
            return None
        t = t_ms / 1000.0
        if self.x is None or self.t is None:
            self.x = number
            self.dx = 0.0
            self.t = t
            return number
        dt = t - self.t
        if dt <= 1e-4:
            return self.x
        dx = (number - self.x) / dt
        a_d = _alpha(dt, 1.0)
        self.dx = a_d * dx + (1.0 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        a = _alpha(dt, cutoff)
        self.x = a * number + (1.0 - a) * self.x
        self.t = t
        ahead = self.x + self.dx * self.lead_s
        if abs(ahead - self.x) > self.cap:
            ahead = self.x + math.copysign(self.cap, ahead - self.x)
        return ahead


class DisplayPose:
    def __init__(self, mode: str = "light"):
        if mode not in MODES:
            raise ValueError(f"pose smoothing must be off|light|normal, not {mode!r}")
        self.mode = mode
        spec = _LIGHT if mode == "light" else _NORMAL
        self._spec = spec
        self._kp: list[list[_Channel]] = []
        self._uv: list[list[_Channel]] = []

    def _channels(self, store: list, count: int, width: int, cap: float) -> list:
        while len(store) < count:
            store.append([
                _Channel(self._spec[0], self._spec[1], self._spec[2], cap) for _ in range(width)
            ])
        return store

    def _row(self, channels, point, t_ms: float):
        if point is None:
            for channel in channels:
                channel.reset()
            return None
        out = []
        for channel, value in zip(channels, point):
            smoothed = channel.update(value, t_ms)
            out.append(None if smoothed is None else round(smoothed, 4))
        return out

    def _cloud(self, points, store, width: int, cap: float, t_ms: float):
        if points is None:
            for row in store:
                for channel in row:
                    channel.reset()
            return None
        channels = self._channels(store, len(points), width, cap)
        return [self._row(channels[i], point, t_ms) for i, point in enumerate(points)]

    def apply(self, keypoints, kp2d, t_ms: float):
        """Smoothed copies. ``None`` in, ``None`` out. Angles are not touched."""
        if self.mode == "off":
            return keypoints, kp2d
        return (
            self._cloud(keypoints, self._kp, 3, _CAP_3D, t_ms),
            self._cloud(kp2d, self._uv, 2, _CAP_2D, t_ms),
        )
