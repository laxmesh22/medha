"""Live PB-MotionNet inference: 64-frame ring buffer -> ONNX Runtime every few frames.

The network only *judges* (exercise / unknown, phase, form, compensation). It never produces degrees and it is
never consulted for safety: the coach applies pause and quality gates before looking at anything here.
If the model file is missing or onnxruntime is not installed, ``available`` is False and the coach runs on
rules alone.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .features import (
    CLASSES, COMP_FLAGS, D_IN, PHASES, WINDOW, frame_vector, imu_features, skeleton_features,
)

log = logging.getLogger(__name__)
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "models" / "motionnet"
UNKNOWN = CLASSES.index("unknown")


def _softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return e / e.sum()


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, float)))


class MotionNetRunner:
    def __init__(self, predict_fn: Optional[Callable] = None, meta: Optional[dict] = None, every: int = 3,
                 min_frames: int = WINDOW // 2):
        """``predict_fn(x (1, WINDOW, D_IN) float32) -> (exercise_logits, phase_logits, form_logit, comp_logits)``."""
        self.predict_fn = predict_fn
        self.meta = meta or {}
        self.every = every
        self.min_frames = min_frames
        th = self.meta.get("thresholds", {})
        e = th.get("energy", {})
        self.energy_thr = e if isinstance(e, dict) else {"skeleton": e, "imu": e, "fused": e}
        self.unknown_prob = float(th.get("unknown_prob", 0.5))
        self.comp_prob = float(th.get("comp_prob", 0.7))
        self.autodetect_conf = float(th.get("autodetect_conf", 0.8))
        # Until ml/validate_real.py has passed this exact model on Physio Buddy recordings, its output is
        # advisory only: shown in the UI, never used to reject reps, add issues or switch exercises.
        rv = self.meta.get("real_validation") or {}
        version = self.meta.get("model_version")
        self.validated = bool(rv.get("passed")) and version is not None and rv.get("model_version") == version
        self.imu_validated = self.validated and bool(rv.get("imu_passed"))
        self.buf: deque = deque(maxlen=WINDOW)
        self._n = 0
        self.latest: Optional[dict] = None

    @property
    def available(self) -> bool:
        return self.predict_fn is not None

    @classmethod
    def from_dir(cls, model_dir: Path = DEFAULT_DIR, **kw) -> "MotionNetRunner":
        model_dir = Path(model_dir)
        onnx_path, meta_path = model_dir / "pb_motionnet.onnx", model_dir / "pb_motionnet.json"
        if not onnx_path.exists():
            log.info("PB-MotionNet not found at %s: rules-only coaching", onnx_path)
            return cls(None, **kw)
        try:
            import onnxruntime as ort
        except ImportError:
            log.warning("onnxruntime not installed: rules-only coaching")
            return cls(None, **kw)
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if meta.get("feature_schema", {}).get("d_in", D_IN) != D_IN:
            log.error("PB-MotionNet feature schema mismatch (model d_in %s, hub %s): disabled",
                      meta["feature_schema"].get("d_in"), D_IN)
            return cls(None, **kw)
        providers = [p for p in ("TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")
                     if p in ort.get_available_providers()]
        sess = ort.InferenceSession(str(onnx_path), providers=providers)
        r = cls(lambda x: sess.run(None, {"x": x}), meta=meta, **kw)
        log.info("PB-MotionNet %s on %s: %s", meta.get("model_version", "?"), sess.get_providers()[0],
                 "validated on real recordings, hybrid coaching on" if r.validated
                 else "NOT validated on real recordings, advisory display only")
        return r

    def reset(self) -> None:
        self.buf.clear()
        self._n = 0
        self.latest = None

    def push(self, sk, angles: Optional[dict], side: str, up_cam, shrug_baseline=None,
             imu: Optional[dict] = None) -> Optional[dict]:
        """Add one frame; returns the latest judgement (refreshed every ``every`` frames) or None."""
        if not self.available:
            return None
        f, ok = skeleton_features(sk, angles, side, up_cam, shrug_baseline)
        fi, oki = imu_features(imu if self.imu_validated else None)
        self.buf.append(frame_vector(f, ok, fi, oki))
        self._n += 1
        if len(self.buf) < self.min_frames:
            return None
        if self.latest is None or self._n % self.every == 0:
            self.latest = self._infer()
        return self.latest

    def _infer(self) -> dict:
        x = np.asarray(self.buf, dtype=np.float32)
        if len(x) < WINDOW:
            x = np.concatenate([np.repeat(x[:1], WINDOW - len(x), 0), x])
        ex, ph, form, comp = self.predict_fn(x[None])
        ex = np.asarray(ex)[0]
        p = _softmax(ex)
        known = ex[:-1]
        energy = float(-np.log(np.exp(known - known.max()).sum()) - known.max())
        ms, mi = bool(x[-1, -2] > 0), bool(x[-1, -1] > 0)
        mode = "fused" if ms and mi else "skeleton" if ms else "imu" if mi else "none"
        thr = self.energy_thr.get(mode, float("inf"))
        k = int(p.argmax())
        is_unknown = mode == "none" or k == UNKNOWN or p[UNKNOWN] > self.unknown_prob or energy > thr
        comp_p = _sigmoid(np.asarray(comp)[0])
        return {
            "model_version": self.meta.get("model_version"),
            "can_veto": self.validated,
            "mode": mode,
            "predicted_exercise": "unknown" if is_unknown else CLASSES[k],
            "top_class": CLASSES[k],
            "confidence": round(float(p[k]), 3),
            "is_unknown": bool(is_unknown),
            "energy": round(energy, 3),
            "phase": PHASES[int(np.asarray(ph)[0, -1].argmax())],
            "form_score": round(float(_sigmoid(np.asarray(form)[0, 0])), 3),   # P(needs fixing)
            "comp_probs": {c: round(float(v), 3) for c, v in zip(COMP_FLAGS, comp_p)},
            "comp_threshold": self.comp_prob,
        }
