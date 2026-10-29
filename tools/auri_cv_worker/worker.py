"""Webcam worker for the station. Runs in the AURI-CV Python 3.12 env, not the hub.

One JSON line per frame on stdout. Logs go to stderr. No image is written or sent.
The engine itself stays in ``external/AURIII`` (teammate code, not modified).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import queue
import sys
import threading
import time

import cv2
import numpy as np

from auri_cv.pipeline import ShoulderAnalysisPipeline
from auri_cv.pose.data_models import LandmarkIndex
from auri_cv.pose.landmarker import AuriPoseLandmarker, VisionTaskRunningMode


def _num(value):
    if value is None:
        return None
    number = float(value)
    if not np.isfinite(number):
        return None
    return round(number, 4)


_STDOUT = threading.Lock()
INFER_WIDTH = 320
# A preview older than this is not worth encoding. The queue holds one frame and
# drops the older one, so the JPEG stays on the frame the skeleton was measured from.
PREVIEW_EVERY_S = 0.0


def _write_line(payload: dict) -> None:
    text = json.dumps(payload, separators=(",", ":")) + "\n"
    with _STDOUT:
        sys.stdout.write(text)
        sys.stdout.flush()


def _fit_width(bgr, width: int):
    height, src_w = bgr.shape[:2]
    if src_w <= width:
        return bgr
    scale = width / float(src_w)
    return cv2.resize(bgr, (width, max(2, int(round(height * scale)))), interpolation=cv2.INTER_AREA)


def _preview_loop(jobs: queue.Queue, stages: dict) -> None:
    """JPEG on its own thread. A full queue is dropped, so encoding never stalls a measurement."""
    while True:
        item = jobs.get()
        if item is None:
            return
        bgr, captured_ms, frame_index = item
        t0 = time.perf_counter()
        ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        enc_ms = (time.perf_counter() - t0) * 1000.0
        if not ok:
            continue
        t1 = time.perf_counter()
        _write_line({
            "kind": "preview",
            "frame": int(frame_index),
            "t_ms": round(captured_ms, 1),
            "w": int(bgr.shape[1]),
            "h": int(bgr.shape[0]),
            "jpeg": base64.b64encode(encoded.tobytes()).decode("ascii"),
        })
        send_ms = (time.perf_counter() - t1) * 1000.0
        with stages["lock"]:
            stages["penc"] += enc_ms
            stages["psend"] += send_ms
            stages["pn"] += 1


def _engine(result) -> dict:
    raw = result.raw
    comp = result.compensation
    quality = result.quality
    return {
        "quality": quality.status.value,
        "quality_score": _num(quality.quality_score),
        "missing": list(quality.missing_landmarks),
        "low_confidence": list(quality.low_confidence_landmarks),
        "elevation_deg": None if raw is None else _num(raw.elevation_deg),
        "flexion_deg": None if raw is None else _num(raw.flexion_deg),
        "abduction_deg": None if raw is None else _num(raw.abduction_deg),
        "plane_deg": None if raw is None else _num(raw.plane_of_elevation_deg),
        "filtered_elevation_deg": _num(result.filtered_elevation_deg),
        "display_elevation_deg": _num(result.channel.display_deg),
        "calibration": result.channel.status.value,
        "rep_state": result.rep_state.value,
        "rep_count": int(result.rep_count),
        "torso_mode": result.torso_mode.value,
        "compensation": None if comp is None else {
            "lateral_lean_deg": _num(comp.lateral_lean_deg),
            "forward_lean_deg": _num(comp.forward_lean_deg),
            "trunk_rotation_deg": _num(comp.trunk_rotation_deg),
            "shoulder_hiking_m": _num(comp.shoulder_hiking_m),
            "warnings": [w.value for w in comp.warnings],
        },
    }


def _landmarks(obs, width: int, height: int) -> list:
    rows = []
    for index in range(33):
        name = LandmarkIndex(index).name
        flat = obs.landmarks_2d.get(name)
        world = obs.landmarks_3d.get(name)
        rows.append({
            "i": index,
            "name": name,
            "u": None if flat is None else round(float(flat.x) * width, 2),
            "v": None if flat is None else round(float(flat.y) * height, 2),
            "vis": None if flat is None else _num(flat.visibility),
            "x": None if world is None else _num(world.x),
            "y": None if world is None else _num(world.y),
            "z": None if world is None else _num(world.z),
        })
    return rows


def _fourcc_name(cap) -> str:
    value = int(cap.get(cv2.CAP_PROP_FOURCC))
    return "".join(chr((value >> (8 * i)) & 0xFF) for i in range(4))


def _log_camera(cap, label: str) -> None:
    logging.info(
        "camera %s %s %dx%d negotiated_fps %.1f exposure %s",
        label,
        _fourcc_name(cap),
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        float(cap.get(cv2.CAP_PROP_FPS)),
        cap.get(cv2.CAP_PROP_EXPOSURE),
    )


def _mean_read_ms(cap, n: int = 8):
    """Camera period while reading back to back. None if the camera returns no frame."""
    for _ in range(2):
        cap.read()
    t0 = time.perf_counter()
    got = 0
    for _ in range(n):
        ok, _frame = cap.read()
        if not ok:
            break
        got += 1
    if got == 0:
        return None
    return (time.perf_counter() - t0) * 1000.0 / got


def _configure(cap, fps: float) -> None:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


def _open_camera(index: int, fps: float):
    """640x480, same image the 320 px inference resizes.

    DirectShow's auto exposure reports 30 fps and then blocks ~75 ms per read
    (~10 fps). Pinning exposure to 1/32 s (-5) keeps the sensor period near 33 ms.
    A longer exposure cannot deliver 18 fps. Media Foundation is the fallback when
    that pin does not stick."""
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if cap.isOpened():
        _configure(cap, fps)
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        cap.set(cv2.CAP_PROP_EXPOSURE, -5)
        period = _mean_read_ms(cap)
        _log_camera(cap, "dshow" if period is None else f"dshow period {period:.0f} ms")
        if period is not None and period <= 45 and int(round(cap.get(cv2.CAP_PROP_EXPOSURE))) == -5:
            return cap
        cap.release()
    cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
    if not cap.isOpened():
        cap.release()
        return None
    _configure(cap, fps)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, -5)
    _log_camera(cap, "msmf")
    return cap


def run(camera: int, side: str, fps: float, preview: bool) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    cap = _open_camera(camera, fps)
    if cap is None:
        logging.error("could not open webcam index %s", camera)
        return 1
    period_ms = max(1, int(round(1000.0 / fps)))
    landmarker = AuriPoseLandmarker(running_mode=VisionTaskRunningMode.VIDEO)
    pipeline = ShoulderAnalysisPipeline(laterality=side)
    logging.info("webcam %s open, side %s, %.0f fps, preview %s", camera, side, fps,
                 "on" if preview else "off")
    jobs: queue.Queue = queue.Queue(maxsize=1)
    stages = {"lock": threading.Lock(), "penc": 0.0, "psend": 0.0, "pn": 0}
    preview_thread = None
    if preview:
        preview_thread = threading.Thread(
            target=_preview_loop, args=(jobs, stages), name="auri-cv-preview", daemon=True,
        )
        preview_thread.start()
    # cap.read blocks for the sensor period. Inference is a separate cost.
    # Running them on one thread adds the two. The capture thread keeps only the
    # newest frame, so a slow pose step drops stale frames instead of waiting.
    holder = {"lock": threading.Lock(), "cond": threading.Condition(), "frame": None,
              "t_ms": 0.0, "read_ms": 0.0, "seq": 0}
    stop_cap = threading.Event()

    def _capture() -> None:
        while not stop_cap.is_set():
            t0 = time.perf_counter()
            ok, bgr = cap.read()
            read_ms = (time.perf_counter() - t0) * 1000.0
            if not ok or bgr is None:
                continue
            snap = bgr.copy()
            with holder["cond"]:
                holder["frame"] = snap
                holder["t_ms"] = time.time() * 1000.0
                holder["read_ms"] = read_ms
                holder["seq"] += 1
                holder["cond"].notify()

    cap_thread = threading.Thread(target=_capture, name="auri-cv-capture", daemon=True)
    cap_thread.start()
    frame_index = 0
    last_preview = 0.0
    seen = 0
    acc = {"read": 0.0, "fit": 0.0, "infer": 0.0, "send": 0.0, "bright": 0.0}
    try:
        while True:
            with holder["cond"]:
                if not holder["cond"].wait_for(lambda: holder["seq"] != seen, timeout=2.0):
                    logging.error("webcam read failed")
                    return 1
                seen = holder["seq"]
                bgr = holder["frame"]
                captured_ms = holder["t_ms"]
                read_ms = holder["read_ms"]
            t_fit = time.perf_counter()
            small = _fit_width(bgr, INFER_WIDTH)
            if preview and captured_ms - last_preview >= PREVIEW_EVERY_S * 1000.0:
                last_preview = captured_ms
                shot = (small.copy(), captured_ms, frame_index)
                try:
                    jobs.put_nowait(shot)
                except queue.Full:
                    try:
                        jobs.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        jobs.put_nowait(shot)
                    except queue.Full:
                        pass
            height, width = small.shape[:2]
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            fit_ms = (time.perf_counter() - t_fit) * 1000.0
            t_inf = time.perf_counter()
            obs = landmarker.detect_video_frame(rgb, timestamp_ms=frame_index * period_ms,
                                                 frame_index=frame_index)
            result = pipeline.process(obs)
            infer_ms = (time.perf_counter() - t_inf) * 1000.0
            t_send = time.perf_counter()
            _write_line({
                "t_ms": round(captured_ms, 1),
                "frame": frame_index,
                "w": int(width),
                "h": int(height),
                "landmarks": _landmarks(obs, width, height),
                "engine": _engine(result),
            })
            send_ms = (time.perf_counter() - t_send) * 1000.0
            acc["read"] += read_ms
            acc["fit"] += fit_ms
            acc["infer"] += infer_ms
            acc["send"] += send_ms
            acc["bright"] += float(small.mean())
            frame_index += 1
            if frame_index % 30 == 0:
                with stages["lock"]:
                    penc = stages["penc"]
                    psend = stages["psend"]
                    pn = stages["pn"]
                    stages["penc"] = stages["psend"] = 0.0
                    stages["pn"] = 0
                logging.info(
                    "stage read %.1f fit %.1f infer %.1f send %.1f preview_enc %.1f preview_send %.1f bright %.1f (n=30 previews=%d)",
                    acc["read"] / 30.0, acc["fit"] / 30.0, acc["infer"] / 30.0, acc["send"] / 30.0,
                    (penc / pn) if pn else 0.0, (psend / pn) if pn else 0.0, acc["bright"] / 30.0, pn,
                )
                acc = {"read": 0.0, "fit": 0.0, "infer": 0.0, "send": 0.0, "bright": 0.0}
    finally:
        stop_cap.set()
        if preview:
            jobs.put(None)
        landmarker.close()
        cap.release()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AURI-CV webcam worker (stdout JSON lines)")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--side", choices=["right", "left"], default="right")
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--preview", choices=["on", "off"], default="on")
    args = parser.parse_args(argv)
    return run(args.camera, args.side, args.fps, args.preview == "on")


if __name__ == "__main__":
    raise SystemExit(main())
