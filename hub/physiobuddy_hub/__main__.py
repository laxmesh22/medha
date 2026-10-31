"""Command line entry point.

    python -m physiobuddy_hub devices                    # list RealSense cameras
    python -m physiobuddy_hub fetch-models               # download pose models for offline use
    python -m physiobuddy_hub run [--debug-video] [--side left] [--record out.bag] [--log]
    python -m physiobuddy_hub run --bag session.bag      # replay a recording through the full pipeline
    python -m physiobuddy_hub run --sim                  # synthetic patient, no camera (UI development)
    python -m physiobuddy_hub run --sim --straps auto    # also ingest AURI-ARM / AURI-TRUNK over BLE
    python -m physiobuddy_hub run --webcam 0             # laptop webcam via the AURI-CV engine
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _cmd_devices(_args) -> None:
    from .capture.realsense import list_devices, measure_up_vector

    devs = list_devices()
    print(json.dumps(devs, indent=2))
    if devs:
        up, info = measure_up_vector()
        print("gravity check:", info, "up_cam =", [round(float(x), 3) for x in up])


def _cmd_fetch_models(args) -> None:
    from .capture.pose import build_pose_estimator

    for name in args.models:
        print("fetching", name, "...")
        build_pose_estimator(name, device="cpu")
    print("models cached under hub/models/rtmlib")


def _strap_slots(spec: str) -> dict:
    """``ADDR=upper_arm,ADDR=forearm``. Empty when the pod's own sensor id is already the slot."""
    from .straps.link import SLOT_IDS

    slots = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        addr, sep, slot = part.partition("=")
        slot = slot.strip()
        if not sep or slot not in SLOT_IDS:
            raise SystemExit(f"--strap-slot needs ADDR=upper_arm|forearm|trunk, not {part!r}")
        slots[addr.strip().upper()] = slot
    return slots


def _merged_slots(spec: str) -> dict:
    """The slot file, then ``--strap-slot`` overwrites any address it names."""
    from .straps.link import load_slot_file

    slots = load_slot_file()
    slots.update(_strap_slots(spec))
    return slots


def _strap_link(spec: str, slots: dict | None = None):
    """``off`` (default) imports nothing from bleak. ``auto`` scans. Otherwise one or more BLE addresses."""
    if spec == "off":
        return None
    from .straps.link import StrapLink

    if spec == "auto":
        return StrapLink(slots=slots)
    return StrapLink([part.strip() for part in spec.split(",") if part.strip()], slots=slots)


def _cmd_run(args) -> None:
    import numpy as np
    import uvicorn

    from .api.server import create_app
    from .capture.pose import build_pose_estimator
    from .capture.realsense import DEFAULT_UP, RealSenseSource, measure_up_vector
    from .pipeline import CameraPipeline

    if args.webcam is not None:
        from .capture.auri_cv import WORLD_UP

        up, up_info = WORLD_UP.copy(), {
            "source": "mediapipe_world_up",
            "tilt_deg": None,
            "note": "MediaPipe world Y is down. This is not a measured gravity vector.",
        }
    elif args.bag or args.sim:
        up, up_info = DEFAULT_UP.copy(), {"source": "assumed_level (replay/sim)", "tilt_deg": None}
    else:
        up, up_info = measure_up_vector(args.serial)
    logging.info("gravity: %s", up_info)

    session_id = time.strftime("%Y%m%d-%H%M%S")
    record = args.record
    if record == "auto":
        record = str(DATA_DIR / "recordings" / f"{session_id}.bag")
    if record:
        Path(record).parent.mkdir(parents=True, exist_ok=True)

    if args.webcam is not None:
        from .capture.auri_cv import WebcamSource

        preview = args.camera_preview != "off"
        source = WebcamSource(camera=args.webcam, side=args.side, preview=preview,
                              exposure=args.cam_exposure)
        source.start()

        class _UnusedPose:
            name = "auri_cv"

            def __call__(self, _bgr):
                raise RuntimeError("webcam frames are not depth-lifted")

        pose = _UnusedPose()
    elif args.sim:
        from .sim import SimPose, SimSource

        source = SimSource()
        pose = SimPose(source)
    else:
        source = RealSenseSource(serial=args.serial, bag_in=args.bag, bag_out=record)
        source.start()
        pose_name = args.pose
        if pose_name == "auto":
            # laptop CPU: lightweight ~18 fps; GPU (Jetson): RTMPose-m with the tiny detector
            pose_name = "rtmpose-m-fast" if args.device == "cuda" else "rtmpose-lightweight"
        pose = build_pose_estimator(pose_name, device=args.device)
    log_dir = DATA_DIR / "sessions" / session_id if args.log else None
    motionnet = None
    if args.motionnet != "off":
        from .ml.motionnet_infer import DEFAULT_DIR, MotionNetRunner

        motionnet = MotionNetRunner.from_dir(Path(args.motionnet) if args.motionnet else DEFAULT_DIR)
    pipeline = CameraPipeline(
        source, pose, up_cam=np.asarray(up), side=args.side, min_score=args.min_score,
        log_dir=log_dir, debug_video=args.debug_video,
        meta={"session": session_id, "pose_model": pose.name, "side": args.side},
        motionnet=motionnet, straps=_strap_link(args.straps, _merged_slots(args.strap_slot)),
        pose_smoothing=args.pose_smoothing, strap_coach=args.strap_coach,
    )
    if args.dataset_dir:
        from .recorder import DatasetRecorder

        pipeline.recorder = DatasetRecorder(Path(args.dataset_dir), up_cam=up)
    pipeline.start()
    status = {"session": session_id, "camera": source.info, "gravity": up_info,
              "pose_model": pose.name, "device": args.device, "log_dir": str(log_dir) if log_dir else None}
    app = create_app(pipeline, status)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        pipeline.stop()
        source.stop()


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="physiobuddy_hub")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("devices", help="list RealSense devices + gravity check")

    f = sub.add_parser("fetch-models", help="download pose models into hub/models")
    f.add_argument("models", nargs="*", default=["rtmpose-lightweight", "rtmpose-m-fast"])

    r = sub.add_parser("run", help="run camera pipeline + web server")
    r.add_argument("--side", choices=["right", "left"], default="right", help="affected shoulder")
    r.add_argument("--pose", default="auto",
                   help="auto | rtmpose-lightweight | rtmpose-m-fast | rtmpose-balanced | rtmpose-performance")
    r.add_argument("--device", default="cpu", help="cpu | cuda (Jetson / NVIDIA GPU)")
    r.add_argument("--min-score", type=float, default=0.4, help="keypoint confidence threshold")
    r.add_argument("--serial", default=None, help="RealSense serial (if several cameras)")
    picture = r.add_mutually_exclusive_group()
    picture.add_argument("--bag", default=None, help="replay a .bag recording instead of the live camera")
    picture.add_argument("--sim", action="store_true", help="synthetic patient, no camera needed (UI development)")
    picture.add_argument("--webcam", nargs="?", const=0, type=int,
                         help="laptop webcam index (default 0) via the external AURI-CV engine")
    r.add_argument("--record", default=None, help="record raw streams to this .bag ('auto' = data/recordings)")
    r.add_argument("--log", action="store_true", help="write per-frame keypoints + angles to data/sessions")
    r.add_argument("--debug-video", action="store_true", help="serve annotated video at /debug/stream.mjpg")
    r.add_argument("--camera-preview", choices=["on", "off"], default="on",
                   help="webcam only: live image under the skeleton (default on). Off is keypoints only")
    r.add_argument("--cam-exposure", default="auto",
                   help="webcam only: auto, or a manual exposure such as -4 (default auto)")
    r.add_argument("--dataset-dir", default=None,
                   help="enable guided recording into this folder (off if omitted)")
    r.add_argument("--motionnet", default=None,
                   help="PB-MotionNet model dir (default hub/models/motionnet; 'off' = rules only)")
    r.add_argument("--pose-smoothing", choices=["off", "light", "normal"], default="light",
                   help="on-screen skeleton only. Angles stay on the measured pose. Default light")
    r.add_argument("--strap-coach", action="store_true",
                   help="count reps from the calibrated straps when the camera cannot see the arm "
                        "(not validated yet; also switchable on the station page)")
    r.add_argument("--straps", default="off",
                   help="off | auto | BLE address[,address]. Default off, so --sim and CI do not open BLE")
    r.add_argument("--strap-slot", default="",
                   help="ADDR=upper_arm|forearm|trunk, repeated with commas. Two unit-1 pods both emit sensor 0")
    r.add_argument("--host", default="0.0.0.0")
    r.add_argument("--port", type=int, default=8000)

    args = p.parse_args(argv)
    if args.cmd == "devices":
        _cmd_devices(args)
    elif args.cmd == "fetch-models":
        _cmd_fetch_models(args)
    elif args.cmd == "run":
        _cmd_run(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
