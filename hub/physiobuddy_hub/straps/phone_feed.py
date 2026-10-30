"""Samples forwarded by the phone. The phone holds the Bluetooth links; this only stores them.

A missing or stale sample is unavailable. Nothing here is turned into an angle.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque

from ..core.strap_kin import SENSORS

STALE_MS = 200
WIRE = {"upper_arm", "forearm", "trunk"}


def _finite4(value) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    try:
        return all(float(v) == float(v) for v in value)
    except (TypeError, ValueError):
        return False


def _finite3(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        out = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if any(v != v for v in out):
        return None
    return out


class PhoneStraps:
    """Same snapshot shape the calibration and the strap geometry already read."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._view: dict[str, dict] = {}
        self._rx: dict[str, deque] = {name: deque(maxlen=400) for name in SENSORS}
        self._new: dict[str, deque] = {name: deque(maxlen=800) for name in SENSORS}
        self._last_any = 0.0
        self.generation = 0

    def receiving(self) -> bool:
        return (time.time() - self._last_any) < 1.5

    def push(self, msg: dict) -> None:
        name = msg.get("sensor")
        if name not in WIRE:
            return
        now = time.time() * 1000.0
        valid = bool(msg.get("valid"))
        quat = msg.get("quat") if valid and _finite4(msg.get("quat")) else None
        if valid and quat is None:
            valid = False
        gyro = _finite3(msg.get("gyro")) if valid else None
        gravity = _finite3(msg.get("gravity")) if valid else None
        seq = msg.get("seq")
        try:
            seq = None if seq is None else int(seq) & 0xFFFF
        except (TypeError, ValueError):
            seq = None
        view = {
            "quat": [round(float(v), 5) for v in quat] if quat else None,
            "gyro": None if gyro is None else [round(v, 5) for v in gyro],
            "gravity": None if gravity is None else [round(v, 5) for v in gravity],
            "t_ms": round(now, 1),
            "valid": valid,
            "accuracy": None,
            "reset": False,
            "age_ms": 0.0,
            "available": bool(valid and quat),
            "seq": seq,
            "_rx": now,
        }
        with self._lock:
            self._last_any = time.time()
            self._view[name] = view
            self._rx[name].append(now)
            if view["available"]:
                self._new[name].append((view["quat"], view["gyro"], seq))

    def _fresh(self, view: dict, now: float) -> dict:
        age = now - float(view.get("_rx", now))
        out = {k: v for k, v in view.items() if k != "_rx"}
        out["age_ms"] = round(age, 1)
        if age > STALE_MS or not view.get("valid"):
            out["quat"] = None
            out["gyro"] = None
            out["gravity"] = None
            out["available"] = False
        return out

    def frame_view(self) -> dict:
        now = time.time() * 1000.0
        with self._lock:
            return {name: self._fresh(self._view[name], now) for name in self._view}

    def snapshot(self) -> dict:
        return self.frame_view()

    def discard_pending(self) -> None:
        with self._lock:
            for hist in self._new.values():
                hist.clear()

    def drain_new(self) -> dict:
        out: dict = {}
        with self._lock:
            for name, hist in self._new.items():
                if not hist:
                    continue
                out[name] = list(hist)
                hist.clear()
        return out

    def status(self) -> dict:
        now = time.time() * 1000.0
        devices = []
        with self._lock:
            views = {name: self._fresh(view, now) for name, view in self._view.items()}
            rates = {}
            for name, rx in self._rx.items():
                while rx and now - rx[0] > 1000:
                    rx.popleft()
                rates[name] = float(len(rx))
        for name in SENSORS:
            view = views.get(name)
            gyro = view.get("gyro") if view else None
            devices.append({
                # Turning speed of the band now. Lets the page show which band is the one being moved.
                "gyro_dps": None if gyro is None else round(math.degrees(math.sqrt(sum(g * g for g in gyro))), 1),
                "seq": view.get("seq") if view else None,
                "name": "phone",
                "address": None,
                "slot": name,
                "connected": bool(view and view.get("available")),
                "link": "connected" if view and view.get("available") else "searching",
                "packet_rate_hz": rates.get(name, 0.0),
                "battery_pct": None,
                "battery_low": False,
                "hardware": None,
            })
        return {"enabled": True, "mode": "phone", "generation": self.generation, "devices": devices}
