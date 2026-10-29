"""Webcam capture via the teammate's AURI-CV engine.

The engine runs in its own Python 3.12 process (``tools/auri_cv_worker/worker.py``).
This module is the hub's 3.10 side: it never imports MediaPipe. Each stdout line becomes
a ``CameraFrame`` plus a ``Skeleton3D`` the hub kinematics already understand.

MediaPipe world landmarks are hip-centred, X to image-right, Y down, Z along the
optical axis. That is the same axis sense as the RealSense camera frame, so the
points are copied across and ``up_cam`` is MediaPipe's world up, ``(0, -1, 0)``.
A landmark with visibility below 0.5, or a missing coordinate, is invalid (NaN), never 0.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from ..datatypes import L_ELBOW, NUM_KEYPOINTS, R_ELBOW, CameraFrame, Intrinsics, Pose2D, Skeleton3D

log = logging.getLogger(__name__)

VIS_MIN = 0.5
# MediaPipe world up. Y-down world, so up is -Y. Same numbers as a level RealSense.
WORLD_UP = np.array([0.0, -1.0, 0.0])

# MediaPipe 33 names we keep. The rest (fingers, heels) have no COCO-17 slot.
_TO_COCO = {
    "NOSE": 0,
    "LEFT_EYE": 1, "RIGHT_EYE": 2,
    "LEFT_EAR": 3, "RIGHT_EAR": 4,
    "LEFT_SHOULDER": 5, "RIGHT_SHOULDER": 6,
    "LEFT_ELBOW": 7, "RIGHT_ELBOW": 8,
    "LEFT_WRIST": 9, "RIGHT_WRIST": 10,
    "LEFT_HIP": 11, "RIGHT_HIP": 12,
    "LEFT_KNEE": 13, "RIGHT_KNEE": 14,
    "LEFT_ANKLE": 15, "RIGHT_ANKLE": 16,
}

def landmark_hint(missing, low_confidence) -> str | None:
    """Why the webcam engine withheld a measurement. None when nobody is in frame.

    The engine (hips mode, one arm) needs both shoulders, both hips, and that arm's
    elbow and wrist, each with visibility and presence at least 0.5. A warning below
    0.7 still counts. This does not invent an angle.
    """
    names = [str(n) for n in list(missing or []) + list(low_confidence or [])]
    if not names:
        return None
    bits = []
    if any("HIP" in n for n in names):
        bits.append("hips")
    if any("WRIST" in n for n in names):
        bits.append("wrist")
    if any("ELBOW" in n for n in names):
        bits.append("elbow")
    if any("SHOULDER" in n for n in names):
        bits.append("both shoulders")
    if not bits:
        return "Step back so the whole arm and both hips are in frame"
    return "Step back: " + " and ".join(bits) + " must be visible"


SETUP_HINT = """Webcam mode needs the AURI-CV checkout (commit 0011377) and its Python 3.12 env:

git clone https://github.com/abdulmueez3-14/AURIII external/AURIII
git -C external/AURIII checkout 0011377
uv venv external/AURIII/.venv --python 3.12
uv pip install --native-tls -r external/AURIII/requirements.txt
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def auri_cv_python(root: Path | None = None) -> Path:
    """Interpreter for the worker. Raises SystemExit with the setup commands if it is missing."""
    root = repo_root() if root is None else root
    python = root / "external" / "AURIII" / ".venv" / "Scripts" / "python.exe"
    package = root / "external" / "AURIII" / "src" / "auri_cv" / "__init__.py"
    if not python.is_file() or not package.is_file():
        raise SystemExit(SETUP_HINT)
    return python


def adapt_line(obj: dict, host_rx_ms: float | None = None):
    """One worker line -> (Pose2D | None, Skeleton3D | None, engine dict, CameraFrame)."""
    width = int(obj.get("w") or 0)
    height = int(obj.get("h") or 0)
    if width < 2 or height < 2:
        width, height = 640, 480
    points = np.full((NUM_KEYPOINTS, 3), np.nan, dtype=np.float64)
    valid = np.zeros(NUM_KEYPOINTS, dtype=bool)
    pixels = np.full((NUM_KEYPOINTS, 2), np.nan, dtype=np.float64)
    scores = np.zeros(NUM_KEYPOINTS, dtype=np.float64)
    for landmark in obj.get("landmarks") or []:
        index = _TO_COCO.get(landmark.get("name"))
        if index is None:
            continue
        u, v = landmark.get("u"), landmark.get("v")
        if u is not None and v is not None:
            pixels[index] = (float(u), float(v))
        vis = landmark.get("vis")
        scores[index] = 0.0 if vis is None else float(vis)
        coords = (landmark.get("x"), landmark.get("y"), landmark.get("z"))
        if vis is not None and float(vis) >= VIS_MIN and all(c is not None for c in coords):
            points[index] = [float(c) for c in coords]
            valid[index] = True
    pose = Pose2D(np.nan_to_num(pixels), scores) if np.isfinite(pixels).any() else None
    engine = dict(obj.get("engine") or {})
    engine["hint"] = landmark_hint(engine.get("missing"), engine.get("low_confidence"))
    # A head and shoulders with no arm still produces a shrug number. The engine saying
    # UNAVAILABLE means the same thing: nothing derived from this frame is a measurement.
    arm_visible = bool(valid[L_ELBOW] or valid[R_ELBOW])
    if engine.get("quality") == "UNAVAILABLE" or not arm_visible:
        skeleton = None
    else:
        skeleton = Skeleton3D(points, valid, None) if valid.any() else None
    captured = obj.get("t_ms")
    engine["latency_ms"] = None if captured is None or host_rx_ms is None else round(host_rx_ms - float(captured), 1)
    engine["capture_fps"] = None
    intrinsics = Intrinsics(width, height, float(width), float(height), width / 2.0, height / 2.0)
    frame = CameraFrame(
        color=np.zeros((height, width, 3), np.uint8),
        depth_m=np.zeros((height, width), np.float32),
        intrinsics=intrinsics,
        timestamp_ms=float(captured if captured is not None else (host_rx_ms or 0.0)),
        frame_number=int(obj.get("frame") or 0),
    )
    return pose, skeleton, engine, frame


class WebcamSource:
    """Spawns the worker and keeps only the newest frame."""

    def __init__(self, camera: int = 0, side: str = "right", fps: float = 30.0,
                 root: Path | None = None, preview: bool = True):
        self.camera = int(camera)
        self.side = side
        self.fps = float(fps)
        self.preview = bool(preview)
        self._preview: bytes | None = None
        self._preview_frame: int | None = None
        self._preview_t_ms: float | None = None
        self._preview_seq = threading.Event()
        self._preview_ring: dict[int, tuple] = {}
        self.root = repo_root() if root is None else root
        self.info = {
            "device": "webcam",
            "source": "auri_cv",
            "camera_index": self.camera,
            "resolution": [640, 480],
            "fps": self.fps,
        }
        self._proc: subprocess.Popen | None = None
        self._threads: list[threading.Thread] = []
        self._queue: queue.Queue = queue.Queue(maxsize=8)
        self._pose = None
        self._skeleton = None
        self._engine: dict = {"quality": None, "latency_ms": None}
        self._times: list[float] = []
        self._ingest_ms = 0.0
        self._ingest_n = 0
        self._preview_ms = 0.0
        self._preview_n = 0

    def start(self) -> None:
        python = auri_cv_python(self.root)
        worker = self.root / "tools" / "auri_cv_worker" / "worker.py"
        checkout = self.root / "external" / "AURIII"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(checkout / "src")
        env["PYTHONUNBUFFERED"] = "1"
        self._proc = subprocess.Popen(
            [str(python), "-u", str(worker), "--camera", str(self.camera),
             "--side", self.side, "--fps", str(self.fps),
             "--preview", "on" if self.preview else "off"],
            cwd=str(checkout),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._threads = [
            threading.Thread(target=self._read_stdout, name="auri-cv-stdout", daemon=True),
            threading.Thread(target=self._read_stderr, name="auri-cv-stderr", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._proc = None

    def latest(self, timeout: float = 1.0):
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
        pose, skeleton, engine, frame = item
        now = time.perf_counter()
        self._times.append(now)
        self._times = [t for t in self._times if now - t <= 1.0]
        engine["capture_fps"] = round(max(0, len(self._times) - 1) / max(now - self._times[0], 1e-3), 1) if len(self._times) > 1 else 0.0
        self._pose, self._skeleton, self._engine = pose, skeleton, engine
        return frame

    def posed_skeleton(self):
        """Skeleton already measured by the worker. The pipeline must not depth-lift this frame."""
        return self._pose, self._skeleton

    def engine_view(self) -> dict:
        return dict(self._engine)

    def latest_preview(self) -> bytes | None:
        """Newest preview JPEG. Not a measurement, and never written to disk."""
        return self._preview

    def preview_for_frame(self, frame: int) -> dict | None:
        """JPEG for one frame id. Kept only in memory, and never recorded."""
        item = self._preview_ring.get(int(frame))
        if item is None:
            return None
        t_ms, jpeg, b64 = item
        return {"frame": int(frame), "t_ms": t_ms, "jpeg": jpeg, "b64": b64}

    def preview_view(self) -> dict | None:
        """Latest JPEG plus the frame id it was measured with. Never recorded."""
        jpeg = self._preview
        if jpeg is None or self._preview_frame is None:
            return None
        return {"frame": self._preview_frame, "t_ms": self._preview_t_ms, "jpeg": jpeg}

    def wait_preview(self, after: int, timeout: float) -> dict | None:
        """Block until a JPEG newer than ``after`` arrives, or the timeout."""
        deadline = time.perf_counter() + max(0.0, timeout)
        while True:
            view = self.preview_view()
            if view is not None and int(view["frame"]) != int(after):
                return view
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return view
            self._preview_seq.wait(min(0.05, remaining))
            self._preview_seq.clear()

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            t0 = time.perf_counter()
            text = raw.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                log.warning("webcam worker sent a non-JSON line")
                continue
            if obj.get("kind") == "preview":
                encoded = obj.get("jpeg")
                frame_no = obj.get("frame")
                if encoded and frame_no is not None:
                    try:
                        jpeg = base64.b64decode(encoded)
                    except (ValueError, TypeError):
                        log.warning("webcam preview was not base64")
                    else:
                        # A late JPEG must not replace a newer frame. The bytes are
                        # never written to the recorder.
                        frame_i = int(frame_no)
                        if self._preview_frame is None or frame_i >= int(self._preview_frame):
                            self._preview = jpeg
                            self._preview_frame = frame_i
                            t_ms = obj.get("t_ms")
                            self._preview_t_ms = None if t_ms is None else float(t_ms)
                            self._preview_seq.set()
                        t_ms = obj.get("t_ms")
                        self._preview_ring[frame_i] = (None if t_ms is None else float(t_ms), jpeg, encoded)
                        while len(self._preview_ring) > 8:
                            self._preview_ring.pop(min(self._preview_ring))
                self._preview_ms += (time.perf_counter() - t0) * 1000.0
                self._preview_n += 1
                if self._preview_n % 10 == 0:
                    log.info("webcam preview ingest %.1f ms over the last 10", self._preview_ms / 10.0)
                    self._preview_ms = 0.0
                    self._preview_n = 0
                continue
            item = adapt_line(obj, host_rx_ms=time.time() * 1000.0)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put(item)
            self._ingest_ms += (time.perf_counter() - t0) * 1000.0
            self._ingest_n += 1
            if self._ingest_n % 30 == 0:
                log.info("webcam ingest %.1f ms/frame over the last 30", self._ingest_ms / 30.0)
                self._ingest_ms = 0.0
                self._ingest_n = 0

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                log.info("webcam: %s", line)
