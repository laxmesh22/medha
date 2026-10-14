"""Shared data types for the hub.

Conventions
-----------
* Camera frame (RealSense): X right, Y down, Z forward (away from the camera), metres.
* Keypoints follow COCO-17 order with *anatomical* sides (``right_shoulder`` = patient's right).
* A measurement that cannot be made is ``None`` with a reason - never 0 (handoff design rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# COCO-17 keypoint indices
NOSE = 0
L_EYE, R_EYE = 1, 2
L_EAR, R_EAR = 3, 4
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16
NUM_KEYPOINTS = 17

KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]

# Quality levels for every reported value.
GOOD = "good"
LOW = "low"
UNAVAILABLE = "unavailable"


@dataclass
class Intrinsics:
    """Pinhole intrinsics of the stream the depth is aligned to (colour)."""

    width: int
    height: int
    fx: float
    fy: float
    ppx: float
    ppy: float
    coeffs: tuple = (0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass
class CameraFrame:
    color: np.ndarray            # H x W x 3, uint8, BGR
    depth_m: np.ndarray          # H x W, float32 metres, 0 = no data (aligned to colour)
    intrinsics: Intrinsics
    timestamp_ms: float          # host clock domain when global time is enabled
    frame_number: int


@dataclass
class Pose2D:
    keypoints_px: np.ndarray     # (17, 2) float, pixel coords in the colour image
    scores: np.ndarray           # (17,) float confidence


@dataclass
class Skeleton3D:
    points: np.ndarray           # (17, 3) float metres in camera frame, NaN where invalid
    valid: np.ndarray            # (17,) bool
    body_depth_m: Optional[float]  # median torso depth, None if torso not found


@dataclass
class Measurement:
    """One clinical value with explicit quality. ``value`` is None when unavailable."""

    value: Optional[float]
    quality: str = UNAVAILABLE
    reason: Optional[str] = None

    @classmethod
    def unavailable(cls, reason: str) -> "Measurement":
        return cls(None, UNAVAILABLE, reason)

    def to_dict(self) -> dict:
        v = None if self.value is None else round(float(self.value), 2)
        return {"value": v, "quality": self.quality, "reason": self.reason}


@dataclass
class CameraAngles:
    side: str                                   # "right" | "left" (affected side)
    movement: Optional[str]                     # flexion | abduction | scaption | extension | rest | None
    elevation: Measurement                      # humerothoracic elevation ("true")
    apparent_elevation: Measurement             # humerus vs world vertical ("apparent")
    plane_of_elevation: Measurement
    elbow_flexion: Measurement
    rotation: Measurement                       # +ER / -IR, elbow-at-side protocol
    trunk_lean_sagittal: Measurement            # + forward
    trunk_lean_lateral: Measurement             # + toward affected side
    shrug_index: Measurement                    # ear-shoulder distance / shoulder width
    flags: list = field(default_factory=list)   # compensation / quality warnings

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "movement": self.movement,
            "elevation": self.elevation.to_dict(),
            "apparent_elevation": self.apparent_elevation.to_dict(),
            "plane_of_elevation": self.plane_of_elevation.to_dict(),
            "elbow_flexion": self.elbow_flexion.to_dict(),
            "rotation": self.rotation.to_dict(),
            "trunk_lean_sagittal": self.trunk_lean_sagittal.to_dict(),
            "trunk_lean_lateral": self.trunk_lean_lateral.to_dict(),
            "shrug_index": self.shrug_index.to_dict(),
            "flags": list(self.flags),
        }
