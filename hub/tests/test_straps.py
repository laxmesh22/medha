"""Strap protocol, clock, and status wiring. No BLE radio."""
import struct
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from physiobuddy_hub.api.server import create_app
from physiobuddy_hub.straps.link import ClockOffset, SensorSample, choose_address, sensor_view
from physiobuddy_hub.straps.protocol import (
    PROTOCOL_VERSION, Status, command, decode_imu_data, decode_raw, decode_status,
)


def _imu(sensor=0, seq=1, t_ms=1000, quat=(1.0, 0.0, 0.0, 0.0), valid=True, accuracy=3, reset=False) -> bytes:
    flags = (1 if valid else 0) | (accuracy << 2) | (0x10 if reset else 0)
    qw, qx, qy, qz = (int(round(v * 16384)) for v in quat)
    return struct.pack("<BBHI4hB", sensor, flags, seq, t_ms, qw, qx, qy, qz, 0)


def _raw(sensor=0, seq=1, t_ms=1000, gyro=(0.5, -0.25, 0.0), gravity=(0.0, 0.0, 9.8)) -> bytes:
    g = tuple(int(round(v * 1024)) for v in gyro)
    a = tuple(int(round(v * 256)) for v in gravity)
    return struct.pack("<BBHI6h", sensor, 0x03, seq, t_ms, *g, *a)


def _status(present=0x01, ok=0x01, drops=4, i2c=0, mv=0) -> bytes:
    return struct.pack("<8BHH4B", 0x01, PROTOCOL_VERSION, 0, 1, 0, 1, present, ok, mv, i2c, 1, 50, 0, drops)


def test_decoder_round_trip_17_37_20_and_status_v2():
    imu, raw = decode_imu_data(_imu(quat=(0.5, -0.5, 0.5, 0.5), seq=7, t_ms=42, reset=True))
    assert raw is None
    assert imu.sensor == 0 and imu.seq == 7 and imu.t_ms == 42 and imu.valid and imu.reset
    assert imu.accuracy == 3
    assert abs(imu.quat[0] - 0.5) < 1e-3 and abs(imu.quat[1] + 0.5) < 1e-3

    both, raw = decode_imu_data(_imu(seq=9, t_ms=80) + _raw(seq=9, t_ms=80))
    assert both.seq == 9 and raw is not None and raw.seq == 9
    assert abs(raw.gyro[0] - 0.5) < 1e-3 and abs(raw.gravity[2] - 9.8) < 0.01

    alone = decode_raw(_raw())
    assert alone.sensor == 0 and alone.gyro is not None and alone.gravity is not None

    status = decode_status(_status(drops=7, i2c=2))
    assert isinstance(status, Status)
    assert status.protocol == 2 and status.firmware == "0.1.0" and status.notify_drops == 7
    assert status.i2c_errors == 2 and status.present == (0,) and status.ok == (0,)
    assert status.battery_mv is None  # 0 means no divider, not an empty cell

    pong = decode_status(struct.pack("<BQI", 0x06, 123456, 99))
    assert pong.host_us == 123456 and pong.t_ms == 99
    assert command(0x06, 99) == struct.pack("<BQ", 0x06, 99)


def test_firmware_module_reexports_the_hub_decoder():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "firmware" / "protocol"))
    import auri_ble

    assert auri_ble.PROTOCOL_VERSION == PROTOCOL_VERSION
    assert auri_ble.decode_imu_data is decode_imu_data


def test_clock_lower_envelope_can_rise_after_the_window():
    clock = ClockOffset(window_ms=30_000)
    clock.observe(1_000, 1_000 - 100)  # offset 100
    clock.observe(2_000, 2_000 - 80)   # offset 80
    clock.observe(3_000, 3_000 - 90)   # offset 90; the envelope stays at 80
    assert clock.offset_ms == 80
    clock.observe(32_001, 32_001 - 95)  # host 2000 (offset 80) has aged out
    assert clock.offset_ms == 90


def test_stale_and_invalid_samples_are_unavailable():
    sample = SensorSample(quat=(1, 0, 0, 0), t_device_ms=1000, valid=True, accuracy=3, reset=False, seq=1,
                          gyro=(0.1, 0, 0), gravity=(0, 0, 9.8))
    fresh = sensor_view(sample, now_ms=1000 + 5000 + 200, offset_ms=5000)
    assert fresh["available"] is True and fresh["quat"][0] == 1

    stale = sensor_view(sample, now_ms=1000 + 5000 + 201, offset_ms=5000)
    assert stale["available"] is False and stale["quat"] is None and stale["gyro"] is None
    assert stale["gravity"] is None and stale["age_ms"] == 201

    invalid = SensorSample((1, 0, 0, 0), 1000, valid=False, accuracy=0, reset=True, seq=2)
    view = sensor_view(invalid, now_ms=1000 + 5000, offset_ms=5000)
    assert view["available"] is False and view["quat"] is None and view["valid"] is False


def test_two_devices_with_one_name_prefer_the_healthy_sensor():
    good = Status(2, "0.1.0", 1, (0,), (0,), None, 0, True, 50, False, 0)
    bad = Status(2, "0.1.0", 1, (0,), (), None, 3, True, 50, False, 0)
    assert choose_address([("AA", bad), ("BB", good)]) == "BB"
    assert choose_address([("AA", bad), ("BB", bad)]) is None
    assert choose_address([("AA", bad)]) == "AA"


def test_fake_link_shows_in_api_status():
    import numpy as np

    from physiobuddy_hub.capture.realsense import DEFAULT_UP
    from physiobuddy_hub.datatypes import NUM_KEYPOINTS, CameraFrame, Intrinsics, Pose2D
    from physiobuddy_hub.pipeline import CameraPipeline

    intr = Intrinsics(848, 480, 425.0, 425.0, 424.0, 240.0)

    class Src:
        n = 0

        def latest(self, timeout=1.0):
            self.n += 1
            return CameraFrame(color=np.zeros((480, 848, 3), np.uint8),
                               depth_m=np.full((480, 848), 2.0, np.float32),
                               intrinsics=intr, timestamp_ms=1000.0 + self.n, frame_number=self.n)

    class Pose:
        name = "fake"

        def __call__(self, _bgr):
            return Pose2D(np.tile([424.0, 240.0], (NUM_KEYPOINTS, 1)), np.full(NUM_KEYPOINTS, 0.9))

    pipeline = CameraPipeline(Src(), Pose(), up_cam=DEFAULT_UP, side="right")

    class FakeLink:
        def status(self):
            return {"enabled": True, "mode": "AA", "devices": [
                {"address": "AA", "connected": True, "sensors": {"upper_arm": {"available": True, "quat": [1, 0, 0, 0]}}}]}

    pipeline.straps = FakeLink()
    pipeline._process(pipeline.source.latest())
    _version, state = pipeline.latest_state()
    assert state["straps"]["devices"][0]["sensors"]["upper_arm"]["available"] is True
    body = TestClient(create_app(pipeline, {"session": "s"})).get("/api/status").json()
    assert body["session"] == "s"
    assert body["straps"]["devices"][0]["address"] == "AA"


def _pipeline():
    import numpy as np

    from physiobuddy_hub.capture.realsense import DEFAULT_UP
    from physiobuddy_hub.datatypes import NUM_KEYPOINTS, CameraFrame, Intrinsics, Pose2D
    from physiobuddy_hub.pipeline import CameraPipeline

    intr = Intrinsics(848, 480, 425.0, 425.0, 424.0, 240.0)

    class Src:
        n = 0

        def latest(self, timeout=1.0):
            self.n += 1
            return CameraFrame(color=np.zeros((480, 848, 3), np.uint8),
                               depth_m=np.full((480, 848), 2.0, np.float32),
                               intrinsics=intr, timestamp_ms=1000.0 + self.n, frame_number=self.n)

    class Pose:
        name = "fake"

        def __call__(self, _bgr):
            return Pose2D(np.tile([424.0, 240.0], (NUM_KEYPOINTS, 1)), np.full(NUM_KEYPOINTS, 0.9))

    return CameraPipeline(Src(), Pose(), up_cam=DEFAULT_UP, side="right")


def test_npose_accepts_still_and_rejects_motion():
    from physiobuddy_hub.straps.calibrate import judge_npose

    still = {"upper_arm": [([1.0, 0.0, 0.0, 0.0], [0.02, 0.0, 0.0])] * 60}
    accepted = judge_npose(still)
    assert accepted["ok"] and accepted["sensors"]["upper_arm"]["samples"] == 60
    moving = {"upper_arm": [([1.0, 0.0, 0.0, 0.0], [0.4, 0.0, 0.0])] * 60}
    rejected = judge_npose(moving)
    assert rejected["ok"] is False and "moving" in rejected["reason"]
    short = {"upper_arm": [([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0])] * 12}
    assert judge_npose(short)["ok"] is False and "fewer than 50" in judge_npose(short)["reason"]


def test_side_change_and_reconnect_clear_calibration():
    pipeline = _pipeline()
    pipeline.strap_cal = object()
    pipeline.set_side("left")
    assert pipeline.strap_cal is None
    pipeline.strap_cal = object()
    pipeline._strap_gen = 1

    class Link:
        generation = 2

        def status(self):
            return {"enabled": True, "mode": "fake", "devices": []}

        def snapshot(self, now_ms=None):
            return {}

    pipeline.straps = Link()
    pipeline._process(pipeline.source.latest())
    assert pipeline.strap_cal is None
    _version, state = pipeline.latest_state()
    assert state["straps"]["calibration"]["state"] == "none"
    assert state["straps"]["angles"] is None


def test_straps_off_leaves_the_state_without_straps():
    pipeline = _pipeline()
    pipeline._process(pipeline.source.latest())
    _version, state = pipeline.latest_state()
    assert "straps" not in state


def test_calibrated_pose_matches_elevation_and_imu_width():
    import numpy as np

    from physiobuddy_hub.core.strap_kin import (
        SENSORS, StrapCalibration, axis_angle, matrix_to_quat, nominal_mount,
    )
    from physiobuddy_hub.ml.features import D_IMU, imu_features

    y_up = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])
    ez = np.array([0.0, 0, 1.0])
    rng = np.random.default_rng(5)
    yaws = {s: axis_angle(ez, rng.uniform(-np.pi, np.pi)) for s in SENSORS}

    def wear(segs):
        out = {}
        for name, rot in segs.items():
            mount = nominal_mount(name, "right")
            out[name] = matrix_to_quat(yaws[name] @ y_up @ rot @ mount.T)
        return out

    still = wear({s: np.eye(3) for s in SENSORS})
    cal = StrapCalibration.from_npose("right", {s: [still[s]] * 8 for s in SENSORS})
    raised = axis_angle(ez, np.radians(90))
    posed = wear({"trunk": np.eye(3), "upper_arm": raised, "forearm": raised})

    class Link:
        generation = 3

        def snapshot(self, now_ms=None):
            return {s: {"available": True, "quat": [float(v) for v in posed[s]], "gyro": [0.0, 0.0, 0.01],
                        "seq": 4} for s in SENSORS}

        def status(self):
            return {"enabled": True, "mode": "fake", "devices": [
                {"name": "AURI-ARM", "connected": True, "packet_rate_hz": 50}]}

    class Net:
        available = True

        def reset(self):
            pass

        def push(self, sk, angles, side, up, shrug=None, imu=None):
            self.imu = imu
            return None

    pipeline = _pipeline()
    pipeline.straps = Link()
    pipeline.strap_cal = cal
    pipeline._strap_gen = 3
    pipeline.nn = Net()
    pipeline._process(pipeline.source.latest())
    _version, state = pipeline.latest_state()
    elev = state["straps"]["angles"]["elevation"]["value"]
    assert elev is not None and abs(elev - 90) < 2
    vec, ok = imu_features(pipeline.nn.imu)
    assert ok and vec.shape == (D_IMU,)
    assert state["coach"]["exercise"]["id"] == "flexion"


def test_two_unit1_pods_take_upper_arm_and_forearm():
    from physiobuddy_hub.straps.link import StrapLink

    arm = "14:63:93:BD:B4:7A"
    fore = "14:63:93:BD:AB:6E"
    plain = StrapLink([arm, fore])
    plain._ensure(arm, "AURI-ARM", None)
    plain._ensure(fore, "AURI-ARM", None)
    plain._on_imu(arm, _imu(seq=1, quat=(1, 0, 0, 0)) + _raw(seq=1))
    plain._on_imu(fore, _imu(seq=2, quat=(0, 1, 0, 0)) + _raw(seq=2))
    collided = plain.snapshot()
    assert set(collided) == {"upper_arm"}

    link = StrapLink([arm, fore], slots={arm: "upper_arm", fore: "forearm"})
    link._ensure(arm, "AURI-ARM", None)
    link._ensure(fore, "AURI-ARM", None)
    link._on_imu(arm, _imu(seq=1, quat=(1, 0, 0, 0)) + _raw(seq=1))
    link._on_imu(fore, _imu(seq=2, quat=(0, 1, 0, 0)) + _raw(seq=2))
    snap = link.snapshot()
    assert snap["upper_arm"]["seq"] == 1
    assert snap["forearm"]["seq"] == 2
    assert abs(snap["upper_arm"]["quat"][0] - 1) < 1e-3
    assert abs(snap["forearm"]["quat"][1] - 1) < 1e-3
    from physiobuddy_hub.straps.protocol import Status

    link._devices[fore].status = Status(2, "0.1.0", 1, (0,), (0,), None, 35, True, 50, False, 0)
    shown = next(dev["sensors"] for dev in link.status()["devices"] if dev["address"] == fore)
    assert set(shown) == {"forearm"}
    slots = {dev["address"]: dev["slot"] for dev in link.status()["devices"]}
    assert slots[arm] == "upper_arm" and slots[fore] == "forearm"


def test_calibration_keeps_a_burst_the_snapshot_would_collapse():
    import asyncio

    from physiobuddy_hub.straps.calibrate import collect_samples
    from physiobuddy_hub.straps.link import StrapLink

    link = StrapLink(["AA:BB:CC:DD:EE:FF"])
    link._ensure("AA:BB:CC:DD:EE:FF", "AURI-ARM", None)

    async def run():
        task = asyncio.create_task(collect_samples(link, 0.25))
        await asyncio.sleep(0.05)
        for seq in range(60):
            link._on_imu("AA:BB:CC:DD:EE:FF", _imu(seq=seq, t_ms=seq * 20) + _raw(seq=seq, t_ms=seq * 20, gyro=(0.0, 0.0, 0.0)))
        return await task

    samples = asyncio.run(run())
    assert link.snapshot()["upper_arm"]["seq"] == 59
    assert len(samples["upper_arm"]) == 60
