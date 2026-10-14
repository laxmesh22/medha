"""Camera pipeline: frame -> 2D pose -> depth lift -> plausibility -> clinical angles -> live state."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

from . import __version__
from .capture.lift import lift_pose
from .core.coach import EXERCISES, Coach
from .core.quality import SegmentTracker
from .core.skeleton_kin import SkeletonKinematics
from .datatypes import (
    L_EAR, L_HIP, L_SHOULDER, LOW, NOSE, R_EAR, R_HIP, R_SHOULDER, CameraFrame, Skeleton3D,
)
from .core.skeleton_kin import SIDE_IDX
from .recorder import DatasetRecorder

log = logging.getLogger(__name__)

# Recommended patient distance for the D455f (design doc §6.1)
DIST_MIN_M, DIST_MAX_M = 1.6, 3.0
# exercise auto-detect: confident votes spanning AUTO_SPAN_S, AUTO_AGREE of the last AUTO_WINDOW_S
AUTO_SPAN_S, AUTO_WINDOW_S, AUTO_AGREE = 1.5, 3.0, 0.8


def leveling_rotation(up_cam: np.ndarray) -> np.ndarray:
    """Rotation taking camera coords to a gravity-levelled display frame (three.js: X right, Y up, Z to viewer)."""
    flip = np.diag([1.0, -1.0, -1.0])                    # RealSense (Y down, Z fwd) -> three.js
    a = flip @ (up_cam / np.linalg.norm(up_cam))
    b = np.array([0.0, 1.0, 0.0])
    v, c = np.cross(a, b), float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))
    return R @ flip


def guidance_codes(sk: Optional[Skeleton3D], side: str) -> list:
    if sk is None:
        return ["NO_PERSON"]
    codes = []
    ok = sk.valid
    if sk.body_depth_m is not None:
        if sk.body_depth_m > DIST_MAX_M:
            codes.append("MOVE_CLOSER")
        elif sk.body_depth_m < DIST_MIN_M:
            codes.append("MOVE_BACK")
    if not (ok[L_SHOULDER] and ok[R_SHOULDER]):
        codes.append("SHOULDERS_NOT_VISIBLE")
    if not (ok[L_HIP] and ok[R_HIP]):
        codes.append("HIPS_NOT_VISIBLE")
    if not (ok[NOSE] or ok[L_EAR] or ok[R_EAR]):
        codes.append("HEAD_NOT_VISIBLE")
    idx = SIDE_IDX[side]
    if not (ok[idx["elbow"]] and ok[idx["wrist"]]):
        codes.append("ARM_NOT_VISIBLE")
    return codes or ["OK"]


class CameraPipeline:
    def __init__(self, source, pose_estimator, up_cam: np.ndarray, side: str = "right",
                 min_score: float = 0.4, log_dir: Optional[Path] = None, debug_video: bool = False,
                 meta: Optional[dict] = None, motionnet=None):
        """``motionnet``: a ``MotionNetRunner`` (hybrid judging) or None for rules-only coaching."""
        self.source = source
        self.pose = pose_estimator
        self.up_cam = np.asarray(up_cam, dtype=float)
        self.min_score = min_score
        self.debug_video = debug_video
        self.meta = meta or {}
        self._R_disp = leveling_rotation(self.up_cam)
        self._lock = threading.Lock()
        self._state: Optional[dict] = None
        self._version = 0
        self._jpeg: Optional[bytes] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._times = deque(maxlen=30)
        self._rest_samples: Optional[list] = None
        self._log_fh = None
        self.coach = Coach("flexion")
        self.recorder = DatasetRecorder(up_cam=self.up_cam)
        self.nn = motionnet if motionnet is not None and motionnet.available else None
        self.autodetect = False
        self._auto_votes: deque = deque()
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(log_dir / "camera.jsonl", "a", encoding="utf-8")
        self.set_side(side)

    # -- control ---------------------------------------------------------------------------
    def set_side(self, side: str) -> None:
        with self._lock:
            self.side = side
            self.kin = SkeletonKinematics(side)
            self.segments = SegmentTracker(side)
            if self.nn is not None:
                self.nn.reset()

    def set_autodetect(self, enabled: bool) -> dict:
        with self._lock:
            self.autodetect = bool(enabled) and self._autodetect_available()
            self._auto_votes.clear()
            return {"enabled": self.autodetect, "available": self._autodetect_available()}

    def _autodetect_available(self) -> bool:
        return self.nn is not None and bool(getattr(self.nn, "validated", False))

    def _autodetect_step(self, t_s: float, nn: Optional[dict]) -> None:
        """Switch exercise when the network is confident for >= AUTO_SPAN_S while the patient rests (lock held)."""
        if not self.autodetect or self.recorder.active:
            return
        while self._auto_votes and self._auto_votes[0][0] < t_s - AUTO_WINDOW_S:
            self._auto_votes.popleft()
        if nn is None or nn.get("can_veto") is not True:
            return
        pred = nn["predicted_exercise"]
        confident = (not nn["is_unknown"] and pred in EXERCISES
                     and nn["confidence"] >= self.nn.autodetect_conf)
        self._auto_votes.append((t_s, pred if confident else None))
        if self.coach.state != "rest" or not confident or pred == self.coach.ex.id:
            return
        same = [t for t, p in self._auto_votes if p == pred]
        if same[-1] - same[0] >= AUTO_SPAN_S and len(same) >= AUTO_AGREE * len(self._auto_votes):
            self.coach.set_exercise(pred)
            self.coach._event("AUTO_EXERCISE", name=self.coach.ex.name)
            self._auto_votes.clear()

    def set_exercise(self, exercise_id: str, target=None) -> dict:
        with self._lock:
            self.coach.set_exercise(exercise_id, target)
            return self.coach.snapshot()

    def set_target(self, target: float) -> None:
        with self._lock:
            self.coach.set_target(target)

    def reset_coach(self) -> None:
        with self._lock:
            self.coach.reset()

    def set_paused(self, paused: bool) -> dict:
        with self._lock:
            self.coach.set_paused(paused)
            return self.coach.snapshot()

    # -- guided dataset recording ------------------------------------------------------------------
    def record_start(self, subject_id: str, side: str, consent: bool, protocol: str = "full") -> dict:
        self.set_side(side)
        with self._lock:
            st = self.recorder.start(subject_id, side, consent, protocol)
            self._apply_record_block()
            return st

    def record_step(self, action: str) -> dict:
        with self._lock:
            st = getattr(self.recorder, action)()
            self._apply_record_block()
            return st

    def record_status(self) -> dict:
        with self._lock:
            return self.recorder.status()

    def _apply_record_block(self) -> None:
        """Point the coach at the current block's exercise (caller holds the lock)."""
        b = self.recorder.block
        if b is None:
            return
        if b.exercise in EXERCISES:
            self.coach.set_exercise(b.exercise, b.target)
        else:
            self.coach.reset()

    def start_rest_capture(self) -> None:
        """Collect shrug baseline from the next frames (patient standing relaxed, arms at sides)."""
        with self._lock:
            self._rest_samples = []

    def rest_capture_result(self) -> dict:
        with self._lock:
            samples = self._rest_samples or []
        if len(samples) < 15:
            return {"ok": False, "n": len(samples), "reason": "not enough valid frames"}
        base = float(np.median(samples))
        spread = float(np.std(samples))
        with self._lock:
            self._rest_samples = None
            if spread > 0.05 * base:
                return {"ok": False, "n": len(samples), "reason": "patient moved during capture"}
            self.kin.set_shrug_baseline(base)
        return {"ok": True, "n": len(samples), "shrug_baseline": round(base, 4)}

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-pipeline", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._log_fh:
            self._log_fh.close()

    # -- outputs ---------------------------------------------------------------------------
    def latest_state(self) -> tuple:
        with self._lock:
            return self._version, self._state

    def latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    # -- loop ------------------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            frame = self.source.latest(timeout=1.0)
            if frame is None:
                continue
            try:
                self._process(frame)
            except Exception:
                log.exception("pipeline step failed")

    def _process(self, frame: CameraFrame) -> None:
        t0 = time.perf_counter()
        pose2d = self.pose(frame.color)
        sk = None
        if pose2d is not None:
            deproject = getattr(self.source, "deproject", None)
            sk = lift_pose(pose2d, frame.depth_m, frame.intrinsics, deproject=deproject,
                           min_score=self.min_score)
        with self._lock:
            kin, segments, side = self.kin, self.segments, self.side
        angles = None
        flags_extra: list = []
        if sk is not None:
            flags_extra = segments.check(sk)
            angles = kin.compute(sk, self.up_cam)
            if flags_extra:
                # implausible geometry: keep numbers visible but downgrade their quality
                for m in (angles.elevation, angles.plane_of_elevation, angles.rotation,
                          angles.elbow_flexion):
                    if m.value is not None:
                        m.quality = LOW
                angles.flags.extend(flags_extra)
            with self._lock:
                if self._rest_samples is not None and angles.shrug_index.value is not None:
                    self._rest_samples.append(angles.shrug_index.value)
        angles_d = angles.to_dict() if angles else None
        with self._lock:
            t_s = frame.timestamp_ms / 1000.0
            nn_out = None if self.nn is None else self.nn.push(sk, angles_d, side, self.up_cam,
                                                               kin.shrug_baseline)
            self._autodetect_step(t_s, nn_out)
            coach_state = self.coach.update(t_s, angles_d, nn=nn_out)
            recorder_state = None
            if self.recorder.active:
                kp3d = None if sk is None else [
                    [round(float(c), 4) for c in p] if v else None for p, v in zip(sk.points, sk.valid)]
                changed = self.recorder.on_frame(frame.timestamp_ms, frame.frame_number, kp3d, angles_d,
                                                 coach_state, self.up_cam)
                if self.recorder.baseline_ready:
                    self.kin.set_shrug_baseline(self.recorder.shrug_baseline)
                    self.recorder.baseline_ready = False
                if changed:
                    self._apply_record_block()
            if self.recorder.blocks:
                recorder_state = self.recorder.status()
        proc_ms = (time.perf_counter() - t0) * 1000.0
        self._times.append(time.perf_counter())
        fps = (len(self._times) - 1) / (self._times[-1] - self._times[0]) if len(self._times) > 1 else 0.0

        state = {
            "type": "camera",
            "t_ms": frame.timestamp_ms,
            "frame": frame.frame_number,
            "fps": round(fps, 1),
            "proc_ms": round(proc_ms, 1),
            "side": side,
            "guidance": guidance_codes(sk, side),
            "body_depth_m": None if sk is None or sk.body_depth_m is None else round(sk.body_depth_m, 3),
            "keypoints": self._display_keypoints(sk),
            "angles": angles.to_dict() if angles else None,
            "segments": segments.medians(),
            "shrug_baseline": kin.shrug_baseline,
            "coach": coach_state,
            "recorder": recorder_state,
            "autodetect": {"enabled": self.autodetect, "available": self._autodetect_available(),
                           "model_loaded": self.nn is not None},
            "scores": None if pose2d is None else [round(float(s), 3) for s in pose2d.scores],
            # normalised 2D keypoints for the "AI vision" overlay (no image needed)
            "kp2d": None if pose2d is None else [
                [round(float(u) / frame.intrinsics.width, 4), round(float(v) / frame.intrinsics.height, 4)]
                for u, v in pose2d.keypoints_px],
            "image_aspect": round(frame.intrinsics.width / frame.intrinsics.height, 4),
        }
        jpeg = self._annotate(frame, pose2d) if self.debug_video else None
        with self._lock:
            self._state = state
            self._version += 1
            if jpeg is not None:
                self._jpeg = jpeg
        if self._log_fh:
            self._write_log(frame, pose2d, sk, state)

    def _display_keypoints(self, sk: Optional[Skeleton3D]) -> Optional[list]:
        if sk is None:
            return None
        pts = sk.points @ self._R_disp.T
        ok = sk.valid
        if ok[L_SHOULDER] and ok[R_SHOULDER]:
            origin = (pts[L_SHOULDER] + pts[R_SHOULDER]) / 2
        else:
            origin = np.nanmean(pts[ok], axis=0) if ok.any() else np.zeros(3)
        out = []
        for i in range(len(pts)):
            out.append([round(float(c), 4) for c in (pts[i] - origin)] if ok[i] else None)
        return out

    def _annotate(self, frame: CameraFrame, pose2d) -> Optional[bytes]:
        import cv2

        img = frame.color.copy()
        if pose2d is not None:
            from rtmlib import draw_skeleton

            img = draw_skeleton(img, pose2d.keypoints_px[None], pose2d.scores[None],
                                kpt_thr=self.min_score)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None

    def _write_log(self, frame, pose2d, sk, state) -> None:
        rec = {
            "t_ms": frame.timestamp_ms,
            "frame": frame.frame_number,
            "hub_version": __version__,
            **self.meta,
            "kp2d": None if pose2d is None else np.round(pose2d.keypoints_px, 2).tolist(),
            "scores": None if pose2d is None else np.round(pose2d.scores, 3).tolist(),
            "kp3d_cam": None if sk is None else [
                [round(float(c), 4) for c in p] if v else None for p, v in zip(sk.points, sk.valid)],
            "angles": state["angles"],
            "guidance": state["guidance"],
        }
        self._log_fh.write(json.dumps(rec) + "\n")
