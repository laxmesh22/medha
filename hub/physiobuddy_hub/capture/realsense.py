"""RealSense D455f capture (design doc §6.1).

* depth + colour 848x480 @ 30 fps, depth aligned to colour
* High Accuracy preset, emitter ON (the D455f's NIR-pass filter needs the projector)
* spatial + temporal filtering in the disparity domain, NO hole filling (filled holes = fake depth)
* world "up" measured once from the camera's built-in accelerometer (camera static on tripod)
* optional .bag recording / playback for replay and offline development
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np

from ..datatypes import CameraFrame, Intrinsics

log = logging.getLogger(__name__)

DEFAULT_UP = np.array([0.0, -1.0, 0.0])  # camera level: up = -Y in RealSense coordinates


def _rs():
    import pyrealsense2 as rs  # lazy: tests and the replay path don't need the SDK
    return rs


def list_devices() -> list:
    rs = _rs()
    out = []
    for dev in rs.context().query_devices():
        info = lambda k: dev.get_info(k) if dev.supports(k) else None  # noqa: E731
        out.append({
            "name": info(rs.camera_info.name),
            "serial": info(rs.camera_info.serial_number),
            "firmware": info(rs.camera_info.firmware_version),
            "usb": info(rs.camera_info.usb_type_descriptor),
        })
    return out


def measure_up_vector(serial: Optional[str] = None, seconds: float = 1.0) -> tuple:
    """Average the accelerometer while static. Returns (up_in_camera_frame, info dict).

    At rest an accelerometer measures the reaction to gravity, i.e. it points *up*.
    librealsense reports D4xx motion data in the depth-sensor coordinate system (X right,
    Y down, Z forward); depth->colour rotation is ~identity, which we ignore here.
    """
    rs = _rs()
    pipe, cfg = rs.pipeline(), rs.config()
    if serial:
        cfg.enable_device(serial)
    cfg.enable_stream(rs.stream.accel)
    samples = []
    try:
        pipe.start(cfg)
        t_end = time.time() + seconds
        while time.time() < t_end:
            frames = pipe.wait_for_frames(1000)
            for f in frames:
                if f.is_motion_frame():
                    d = f.as_motion_frame().get_motion_data()
                    samples.append((d.x, d.y, d.z))
    except Exception as exc:  # no IMU / busy device -> assume level camera
        log.warning("accelerometer unavailable (%s); assuming camera is level", exc)
        return DEFAULT_UP.copy(), {"source": "assumed_level", "tilt_deg": None}
    finally:
        try:
            pipe.stop()
        except Exception:
            pass
    if len(samples) < 10:
        return DEFAULT_UP.copy(), {"source": "assumed_level", "tilt_deg": None}
    a = np.asarray(samples)
    mean = a.mean(axis=0)
    g = float(np.linalg.norm(mean))
    if abs(g - 9.81) > 0.6 or float(a.std(axis=0).max()) > 0.3:
        log.warning("camera not static during gravity capture (|a|=%.2f); assuming level", g)
        return DEFAULT_UP.copy(), {"source": "assumed_level", "tilt_deg": None}
    up = mean / g
    tilt = float(np.degrees(np.arccos(np.clip(np.dot(up, DEFAULT_UP), -1, 1))))
    return up, {"source": "camera_imu", "tilt_deg": round(tilt, 2)}


class RealSenseSource:
    """Grabs aligned frames on a background thread; ``latest()`` returns the newest frame only.

    Dropping stale frames keeps latency low when pose estimation is slower than 30 fps.
    """

    def __init__(self, width: int = 848, height: int = 480, fps: int = 30,
                 serial: Optional[str] = None, bag_in: Optional[str] = None,
                 bag_out: Optional[str] = None, realtime_playback: bool = True):
        self.width, self.height, self.fps = width, height, fps
        self.serial, self.bag_in, self.bag_out = serial, bag_in, bag_out
        self.realtime_playback = realtime_playback
        self._pipe = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Optional[CameraFrame] = None
        self._new = threading.Event()
        self.info: dict = {}

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        rs = _rs()
        cfg = rs.config()
        if self.bag_in:
            cfg.enable_device_from_file(self.bag_in, repeat_playback=True)
        else:
            if self.serial:
                cfg.enable_device(self.serial)
            cfg.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, self.fps)
            cfg.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)
            if self.bag_out:
                cfg.enable_record_to_file(self.bag_out)
        self._pipe = rs.pipeline()
        profile = self._pipe.start(cfg)
        dev = profile.get_device()
        if self.bag_in:
            dev.as_playback().set_real_time(self.realtime_playback)
        else:
            self._configure_depth_sensor(dev.first_depth_sensor())
        depth_sensor = dev.first_depth_sensor()
        self._depth_scale = depth_sensor.get_depth_scale()
        self._align = rs.align(rs.stream.color)
        self._to_disp = rs.disparity_transform(True)
        self._from_disp = rs.disparity_transform(False)
        self._spatial = rs.spatial_filter()
        self._temporal = rs.temporal_filter()
        cprof = profile.get_stream(rs.stream.color).as_video_stream_profile()
        ci = cprof.get_intrinsics()
        self._rs_intr = ci
        self.intrinsics = Intrinsics(ci.width, ci.height, ci.fx, ci.fy, ci.ppx, ci.ppy,
                                     tuple(ci.coeffs))
        self.info = {
            "device": dev.get_info(rs.camera_info.name) if dev.supports(rs.camera_info.name) else "?",
            "source": "bag" if self.bag_in else "live",
            "recording": self.bag_out,
            "resolution": [ci.width, ci.height],
            "fps": self.fps,
            "distortion_model": str(ci.model),
        }
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="realsense", daemon=True)
        self._thread.start()
        log.info("RealSense started: %s", self.info)

    def _configure_depth_sensor(self, sensor) -> None:
        rs = _rs()

        def try_set(opt, value):
            try:
                if sensor.supports(opt):
                    sensor.set_option(opt, value)
            except Exception as exc:
                log.warning("could not set %s=%s: %s", opt, value, exc)

        try_set(rs.option.visual_preset, int(rs.rs400_visual_preset.high_accuracy))
        try_set(rs.option.emitter_enabled, 1)          # required for the D455f NIR-pass filter
        try_set(rs.option.global_time_enabled, 1)      # timestamps in host clock domain

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._pipe:
            try:
                self._pipe.stop()
            except Exception:
                pass

    # -- frames ----------------------------------------------------------------------------
    def deproject(self, u: float, v: float, z: float) -> tuple:
        """Exact deprojection with the colour stream's distortion model."""
        return tuple(_rs().rs2_deproject_pixel_to_point(self._rs_intr, [u, v], z))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frames = self._pipe.wait_for_frames(2000)
            except Exception as exc:
                log.warning("frame wait failed: %s", exc)
                continue
            frames = self._align.process(frames)
            depth = frames.get_depth_frame()
            color = frames.get_color_frame()
            if not depth or not color:
                continue
            depth = self._to_disp.process(depth)
            depth = self._spatial.process(depth)
            depth = self._temporal.process(depth)
            depth = self._from_disp.process(depth)
            depth_m = np.asanyarray(depth.get_data()).astype(np.float32) * self._depth_scale
            frame = CameraFrame(
                color=np.asanyarray(color.get_data()).copy(),
                depth_m=depth_m,
                intrinsics=self.intrinsics,
                timestamp_ms=float(color.get_timestamp()),
                frame_number=int(color.get_frame_number()),
            )
            with self._lock:
                self._latest = frame
            self._new.set()

    def latest(self, timeout: float = 1.0) -> Optional[CameraFrame]:
        if not self._new.wait(timeout):
            return None
        with self._lock:
            self._new.clear()
            return self._latest
