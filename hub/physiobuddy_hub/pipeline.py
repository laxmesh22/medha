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
from .core.display_gate import LandmarkGate, close_hint
from .core.pose_smooth import DisplayPose
from .straps.calibrate import (
    judge_npose, load_worn_mount, placement_problem, save_worn_mount, strap_frame, strap_pose,
)
from .straps.phone_feed import PhoneStraps
from .core.quality import SegmentTracker
from .core.skeleton_kin import SkeletonKinematics
from .datatypes import (
    L_EAR, L_HIP, L_SHOULDER, LOW, NOSE, R_EAR, R_HIP, R_SHOULDER, CameraFrame, Skeleton3D,
)
from .core.skeleton_kin import SIDE_IDX

log = logging.getLogger(__name__)

RECORDING_OFF_REASON = "Recording is off: start the hub with --dataset-dir <folder>"


class RecordingOff(Exception):
    """Record was called when the hub was started without ``--dataset-dir``."""

    def __init__(self):
        super().__init__(RECORDING_OFF_REASON)


def recording_off_status() -> dict:
    """Status payload when no dataset directory was given. ``enabled`` is what the UI reads."""
    return {
        "enabled": False, "active": False, "done": False, "announce": None, "announce_id": 0,
        "block": None, "reason": RECORDING_OFF_REASON,
    }


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
                 meta: Optional[dict] = None, motionnet=None, straps=None,
                 pose_smoothing: str = "light"):
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
        self.recorder = None  # set by --dataset-dir; never the training folder by default
        self.nn = motionnet if motionnet is not None and motionnet.available else None
        self.straps = straps  # StrapLink, or None when --straps off. Not used by the coach.
        self.phone = PhoneStraps()  # samples the phone forwards; the phone holds Bluetooth
        self.strap_cal = None
        self._strap_cal_time = None
        self._strap_gen = None
        self.pose_smoothing = pose_smoothing
        self._display = DisplayPose(pose_smoothing)
        self._gate = LandmarkGate()
        self.autodetect = False
        self._auto_votes: deque = deque()
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(log_dir / "camera.jsonl", "a", encoding="utf-8")
        self.set_side(side)

    # -- control ---------------------------------------------------------------------------
    def set_side(self, side: str) -> None:
        with self._lock:
            changed = getattr(self, "side", None) != side
            self.side = side
            self.kin = SkeletonKinematics(side)
            self.segments = SegmentTracker(side)
            if self.nn is not None:
                self.nn.reset()
            if changed:
                self.strap_cal = None
                self._strap_cal_time = None
                self._load_worn_mount()

    def set_autodetect(self, enabled: bool) -> dict:
        with self._lock:
            self.autodetect = bool(enabled) and self._autodetect_available()
            self._auto_votes.clear()
            return {"enabled": self.autodetect, "available": self._autodetect_available()}

    def _autodetect_available(self) -> bool:
        return self.nn is not None and bool(getattr(self.nn, "validated", False))

    def _autodetect_step(self, t_s: float, nn: Optional[dict]) -> None:
        """Switch exercise when the network is confident for >= AUTO_SPAN_S while the patient rests (lock held)."""
        if not self.autodetect or (self.recorder is not None and self.recorder.active):
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
        if self.recorder is None:
            raise RecordingOff()
        self.set_side(side)
        with self._lock:
            st = self.recorder.start(subject_id, side, consent, protocol)
            st["enabled"] = True
            self._apply_record_block()
            return st

    def record_step(self, action: str) -> dict:
        if self.recorder is None:
            raise RecordingOff()
        with self._lock:
            st = getattr(self.recorder, action)()
            st["enabled"] = True
            self._apply_record_block()
            return st

    def record_status(self) -> dict:
        if self.recorder is None:
            return recording_off_status()
        with self._lock:
            st = self.recorder.status()
            st["enabled"] = True
            return st

    def _apply_record_block(self) -> None:
        """Point the coach at the current block's exercise (caller holds the lock)."""
        if self.recorder is None:
            return
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
        if self.straps is not None:
            self.straps.start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-pipeline", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.straps is not None:
            self.straps.stop()
        if self._log_fh:
            self._log_fh.close()

    def strap_source(self):
        """The phone feed while it is sending, otherwise the laptop Bluetooth link."""
        if self.phone.receiving():
            return self.phone
        return self.straps

    def _sync_strap_cal(self) -> None:
        """A reconnect gives the BNO a new yaw reference, so the saved N-pose no longer applies."""
        src = self.strap_source()
        if self.strap_cal is None or src is None:
            return
        gen = getattr(src, "generation", None)
        if gen is not None and gen != self._strap_gen:
            self.strap_cal = None
            self._strap_cal_time = None

    def _load_worn_mount(self) -> None:
        """Use the last position the sensors were worn in, until a new calibration replaces it."""
        loaded = load_worn_mount(self.side)
        if loaded is None:
            return
        self.strap_cal, self._strap_cal_time = loaded
        # The phone's generation stays 0. Leaving this unset made the first phone sample look like a new
        # sensor and deleted the worn position.
        phone = getattr(self, "phone", None)
        self._strap_gen = getattr(phone, "generation", 0) if phone is not None else None

    def calibration_view(self) -> dict:
        self._sync_strap_cal()
        slots = []
        for name in ("upper_arm", "forearm", "trunk"):
            if self.strap_cal is None or name not in self.strap_cal.ref:
                slots.append({"sensor": name, "state": "none", "offset_deg": None})
                continue
            raised = bool(self.strap_cal.forward_raise.get(name))
            tilt = self.strap_cal.gravity_offset_deg(name)
            slots.append({
                "sensor": name,
                "state": ("lean" if name == "trunk" else "raise") if raised else "npose",
                "offset_deg": None if tilt is None else round(tilt, 2),
            })
        if self.strap_cal is None:
            return {"state": "none", "time": None, "sensors": [], "slots": slots}
        raised = sorted(name for name, done in self.strap_cal.forward_raise.items() if done and name != "trunk")
        return {
            "state": "npose+raise" if raised else "npose",
            "time": self._strap_cal_time,
            "sensors": sorted(self.strap_cal.ref),
            "forward_raise": raised,
            "forward_lean": bool(self.strap_cal.forward_raise.get("trunk")),
            "slots": slots,
        }

    def finish_npose(self, samples: dict) -> dict:
        judged = judge_npose(samples)
        sensors = judged.get("sensors") or {}
        if not judged["ok"]:
            return {"ok": False, "reason": judged["reason"], "sensors": sensors}
        with self._lock:
            from .core.strap_kin import StrapCalibration

            self.strap_cal = StrapCalibration.from_npose(self.side, judged["quats"])
            self._strap_cal_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            src = self.strap_source() or self.phone
            self._strap_gen = None if src is None else getattr(src, "generation", None)
            save_worn_mount(self.strap_cal, self._strap_cal_time)
        return {"ok": True, "sensors": sensors, "calibration": self.calibration_view()}

    def finish_raise(self, samples: dict) -> dict:
        self._sync_strap_cal()
        if self.strap_cal is None:
            return {"ok": False, "reason": "stand still in the N-pose first", "refined": []}
        problem = placement_problem("raise", samples)
        if problem:
            return {"ok": False, "reason": problem, "refined": []}
        before = set(self.strap_cal.forward_raise)
        # The way the arm actually moved sets forward. Gyro is only a fallback.
        self.strap_cal.refine_from_raise_direction(samples)
        gyro = {}
        for name, rows in samples.items():
            rates = [g for _q, g in rows if g is not None]
            if rates:
                gyro[name] = np.degrees(np.asarray(rates, float))
        self.strap_cal.refine_with_forward_raise(gyro)
        refined = sorted(set(self.strap_cal.forward_raise) - before)
        if not refined:
            return {"ok": False, "reason": "raise not seen; move the straight arm slowly forward", "refined": []}
        self._strap_cal_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_worn_mount(self.strap_cal, self._strap_cal_time)
        return {"ok": True, "refined": refined, "calibration": self.calibration_view()}

    def finish_lean(self, samples: dict) -> dict:
        self._sync_strap_cal()
        if self.strap_cal is None:
            return {"ok": False, "reason": "stand still in the N-pose first"}
        if "trunk" not in self.strap_cal.ref:
            return {"ok": False, "reason": "the waist strap was not in the N-pose"}
        problem = placement_problem("lean", samples)
        if problem:
            return {"ok": False, "reason": problem}
        # A new lean replaces the old forward: undo the flag so the refine runs again on this mount.
        had = self.strap_cal.forward_raise.pop("trunk", None)
        if not self.strap_cal.refine_trunk_from_lean(samples):
            if had:
                self.strap_cal.forward_raise["trunk"] = had
            return {"ok": False, "reason": "lean not seen; bend slowly forward from the hips"}
        self._strap_cal_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_worn_mount(self.strap_cal, self._strap_cal_time)
        return {"ok": True, "calibration": self.calibration_view()}

    def strap_status(self) -> Optional[dict]:
        # The phone feed is always there. Show its three slots even before the first sample,
        # so the station page is not blank while the phone is still connecting.
        link = self.strap_source() or self.phone
        if link is None:
            return None
        try:
            return link.status()
        except Exception:
            log.exception("strap status failed")
            return {"enabled": True, "error": "unavailable"}

    # -- outputs ---------------------------------------------------------------------------
    def latest_state(self) -> tuple:
        with self._lock:
            return self._version, self._state

    def latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def latest_preview(self) -> Optional[bytes]:
        """Webcam preview JPEG. Separate from measurements and never recorded."""
        fn = getattr(self.source, "latest_preview", None)
        return None if fn is None else fn()

    def wait_preview(self, after: int, timeout: float):
        """Newest preview JPEG newer than ``after``. Not a measurement."""
        fn = getattr(self.source, "wait_preview", None)
        return None if fn is None else fn(after, timeout)

    def preview_for_frame(self, frame):
        """Preview JPEG for this frame id only. Missing stays None, never a neighbour frame."""
        fn = getattr(self.source, "preview_for_frame", None)
        if fn is None or frame is None:
            return None
        return fn(frame)

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
        # A webcam frame already carries a Skeleton3D from MediaPipe world landmarks.
        # Depth-lifting those pixels would invent a camera the webcam does not have.
        posed = getattr(self.source, "posed_skeleton", None)
        if posed is not None:
            pose2d, sk = posed()
        else:
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
        self._sync_strap_cal()
        strap_angles, imu_block, pose = (None, None, None)
        link = self.strap_source()
        if link is not None and self.strap_cal is not None:
            # frame_view does not wait if a strap callback holds the lock. snapshot() would.
            view = link.frame_view() if hasattr(link, "frame_view") else link.snapshot()
            strap_angles, imu_block = strap_frame(self.strap_cal, view)
            pose = strap_pose(self.strap_cal, view)
        with self._lock:
            t_s = frame.timestamp_ms / 1000.0
            nn_out = None if self.nn is None else self.nn.push(sk, angles_d, side, self.up_cam,
                                                               kin.shrug_baseline, imu=imu_block)
            self._autodetect_step(t_s, nn_out)
            coach_state = self.coach.update(t_s, angles_d, nn=nn_out)
            if self.recorder is None:
                recorder_state = recording_off_status()
            else:
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
                    recorder_state["enabled"] = True
        proc_ms = (time.perf_counter() - t0) * 1000.0
        self._times.append(time.perf_counter())
        fps = (len(self._times) - 1) / (self._times[-1] - self._times[0]) if len(self._times) > 1 else 0.0

        raw_kp = self._display_keypoints(sk)
        raw_2d = None
        if pose2d is not None:
            width, height = frame.intrinsics.width, frame.intrinsics.height
            raw_2d = []
            for u, v in pose2d.keypoints_px:
                if not (np.isfinite(u) and np.isfinite(v)):
                    raw_2d.append(None)
                else:
                    raw_2d.append([round(float(u) / width, 4), round(float(v) / height, 4)])
        # Drawn skeleton only. angles above stay on the measured pose.
        disp_kp, disp_2d = self._display.apply(raw_kp, raw_2d, frame.timestamp_ms)
        score_row = None if pose2d is None else [None if not np.isfinite(s) else round(float(s), 3) for s in pose2d.scores]
        overlay = self._gate.update(raw_2d, score_row, frame.timestamp_ms)
        state = {
            "type": "camera",
            "t_ms": frame.timestamp_ms,
            "frame": frame.frame_number,
            "fps": round(fps, 1),
            "proc_ms": round(proc_ms, 1),
            "side": side,
            "pose_smoothing": self.pose_smoothing,
            "guidance": guidance_codes(sk, side),
            "body_depth_m": None if sk is None or sk.body_depth_m is None else round(sk.body_depth_m, 3),
            "keypoints": disp_kp,
            "angles": angles.to_dict() if angles else None,
            "segments": segments.medians(),
            "shrug_baseline": kin.shrug_baseline,
            "coach": coach_state,
            "recorder": recorder_state,
            "autodetect": {"enabled": self.autodetect, "available": self._autodetect_available(),
                           "model_loaded": self.nn is not None},
            "scores": score_row,
            # normalised 2D keypoints for the overlay. Display follow only; not the measurement.
            "kp2d": disp_2d,
            "overlay": overlay,
            "close_hint": close_hint(raw_2d, score_row),
            "image_aspect": round(frame.intrinsics.width / frame.intrinsics.height, 4),
            "strap_pose": pose,
        }
        engine = getattr(self.source, "engine_view", None)
        if engine is not None:
            state["auri_cv"] = engine()
        straps = self.strap_status()
        if straps is not None:
            straps["angles"] = strap_angles
            straps["calibration"] = self.calibration_view()
            state["straps"] = straps
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
