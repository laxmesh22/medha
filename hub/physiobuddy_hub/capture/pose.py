"""2D pose estimation backends.

Default: RTMPose (Apache-2.0) via ``rtmlib`` + ONNX Runtime. COCO-17 keypoints with anatomical sides.
On Jetson use ``device="cuda"`` with the Jetson onnxruntime-gpu wheel (docs/setup_jetson.md).

Models are cached under ``hub/models/rtmlib`` (not ~/.cache) so the Jetson can run offline at the venue:
run ``python -m physiobuddy_hub fetch-models`` once while online.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np

from ..datatypes import L_SHOULDER, NUM_KEYPOINTS, Pose2D, R_SHOULDER

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def _use_local_model_cache() -> None:
    # rtmlib caches downloads under $TORCH_HOME/hub
    os.environ.setdefault("TORCH_HOME", str(MODELS_DIR / "rtmlib"))


def select_patient(keypoints: np.ndarray, scores: np.ndarray,
                   prev_centre: Optional[np.ndarray] = None,
                   min_mean_score: float = 0.3) -> Optional[int]:
    """Pick the patient among detected people.

    Largest confident person wins; if we tracked someone last frame, strongly prefer whoever is
    nearest to them (stops the skeleton jumping to a physio walking behind the patient).
    """
    best, best_cost = None, None
    for i in range(len(keypoints)):
        s = scores[i]
        if float(np.mean(s)) < min_mean_score:
            continue
        ok = s >= 0.3
        if ok.sum() < 4:
            continue
        pts = keypoints[i][ok]
        area = float(np.ptp(pts[:, 0]) * np.ptp(pts[:, 1]))
        cost = -area * float(np.mean(s))
        if prev_centre is not None:
            centre = keypoints[i][[L_SHOULDER, R_SHOULDER]].mean(axis=0)
            dist = float(np.linalg.norm(centre - prev_centre))
            cost += dist * dist * 50.0
        if best_cost is None or cost < best_cost:
            best, best_cost = i, cost
    return best


class RtmlibPose:
    """YOLOX detector + RTMPose with detection every ``det_frequency`` frames.

    ``mode="m-fast"`` = tiny detector + RTMPose-m: a single patient filling the frame does not need
    the large detector, which dominates CPU time in rtmlib's "balanced" mode.
    """

    def __init__(self, mode: str = "lightweight", device: str = "cpu",
                 backend: str = "onnxruntime", det_frequency: int = 5):
        _use_local_model_cache()
        from functools import partial

        from rtmlib import Body, PoseTracker  # heavy import, keep lazy

        self.name = f"rtmpose-{mode}"
        solution, mode_kw = Body, {"mode": mode}
        if mode == "m-fast":
            light, bal = Body.MODE["lightweight"], Body.MODE["balanced"]
            solution = partial(Body, det=light["det"], det_input_size=light["det_input_size"],
                               pose=bal["pose"], pose_input_size=bal["pose_input_size"])
            mode_kw = {}
        self._tracker = PoseTracker(solution, det_frequency=det_frequency, tracking=False,
                                    backend=backend, device=device, **mode_kw)
        self._prev_centre: Optional[np.ndarray] = None

    def __call__(self, bgr: np.ndarray) -> Optional[Pose2D]:
        keypoints, scores = self._tracker(bgr)
        keypoints = np.asarray(keypoints, dtype=np.float64)
        scores = np.asarray(scores, dtype=np.float64)
        if keypoints.ndim != 3 or keypoints.shape[0] == 0 or keypoints.shape[1] != NUM_KEYPOINTS:
            self._prev_centre = None
            return None
        idx = select_patient(keypoints, scores, self._prev_centre)
        if idx is None:
            self._prev_centre = None
            return None
        kp, sc = keypoints[idx], scores[idx]
        self._prev_centre = kp[[L_SHOULDER, R_SHOULDER]].mean(axis=0)
        return Pose2D(keypoints_px=kp, scores=sc)


def build_pose_estimator(name: str, device: str = "cpu"):
    name = name.lower()
    if name in ("rtmpose", "rtmpose-lightweight"):
        return RtmlibPose(mode="lightweight", device=device)
    if name == "rtmpose-m-fast":
        return RtmlibPose(mode="m-fast", device=device)
    if name == "rtmpose-balanced":
        return RtmlibPose(mode="balanced", device=device)
    if name == "rtmpose-performance":
        return RtmlibPose(mode="performance", device=device)
    raise ValueError(f"unknown pose backend: {name}")
