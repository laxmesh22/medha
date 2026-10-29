import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import make_skeleton
from physiobuddy_hub.api.server import create_app
from physiobuddy_hub.capture.realsense import DEFAULT_UP
from physiobuddy_hub.core.quality import SegmentTracker
from physiobuddy_hub.datatypes import CameraFrame, Intrinsics, NUM_KEYPOINTS, Pose2D, R_WRIST
from physiobuddy_hub.pipeline import CameraPipeline, guidance_codes, leveling_rotation


def test_leveling_rotation_level_camera_flips_axes():
    R = leveling_rotation(DEFAULT_UP)
    np.testing.assert_allclose(R @ np.array([1.0, 2.0, 3.0]), [1.0, -2.0, -3.0], atol=1e-9)


def test_leveling_rotation_maps_tilted_up_to_display_up():
    up = np.array([0.1, -0.98, 0.15])
    up /= np.linalg.norm(up)
    np.testing.assert_allclose(leveling_rotation(up) @ up, [0, 1, 0], atol=1e-9)


def test_guidance_codes():
    assert guidance_codes(None, "right") == ["NO_PERSON"]
    assert guidance_codes(make_skeleton(), "right") == ["OK"]
    sk = make_skeleton(drop=(R_WRIST,))
    sk.body_depth_m = 3.6
    codes = guidance_codes(sk, "right")
    assert "MOVE_CLOSER" in codes and "ARM_NOT_VISIBLE" in codes


def test_segment_tracker_flags_sudden_arm_length_change():
    tr = SegmentTracker("right", min_history=5)
    for _ in range(10):
        assert tr.check(make_skeleton()) == []
    sk = make_skeleton()
    sk.points[8] = sk.points[6] + (sk.points[8] - sk.points[6]) * 1.4  # elbow 40 % further away
    assert "IMPLAUSIBLE_UPPER_ARM" in tr.check(sk)


# --- end-to-end with fakes (no camera, no model) -------------------------------------------
INTR = Intrinsics(848, 480, 425.0, 425.0, 424.0, 240.0)


class FakeSource:
    def __init__(self):
        self.n = 0

    def latest(self, timeout=1.0):
        self.n += 1
        return CameraFrame(color=np.zeros((480, 848, 3), np.uint8),
                           depth_m=np.full((480, 848), 2.0, np.float32),
                           intrinsics=INTR, timestamp_ms=1000.0 + self.n, frame_number=self.n)


class FakePose:
    name = "fake"

    def __call__(self, bgr):
        kp = np.tile([424.0, 240.0], (NUM_KEYPOINTS, 1))
        kp[5], kp[6] = [480, 200], [370, 200]   # shoulders
        kp[11], kp[12] = [460, 330], [390, 330]  # hips
        kp[8], kp[10] = [360, 270], [355, 330]  # right elbow, wrist
        kp[3], kp[4] = [450, 150], [400, 150]   # ears
        return Pose2D(kp, np.full(NUM_KEYPOINTS, 0.9))


@pytest.fixture
def pipeline():
    p = CameraPipeline(FakeSource(), FakePose(), up_cam=DEFAULT_UP, side="right")
    p._process(p.source.latest())
    return p


def test_pipeline_state_contents(pipeline):
    version, state = pipeline.latest_state()
    assert version == 1
    assert state["type"] == "camera"
    assert state["angles"]["elevation"]["value"] is not None
    assert len(state["keypoints"]) == NUM_KEYPOINTS
    assert state["keypoints"][0] is not None
    assert len(state["kp2d"]) == NUM_KEYPOINTS and 0 <= state["kp2d"][5][0] <= 1
    assert state["coach"]["exercise"]["id"] == "flexion"


def test_api_exercise_and_target(pipeline):
    client = TestClient(create_app(pipeline, {}))
    assert client.post("/api/exercise", json={"id": "abduction"}).json()["coach"]["exercise"]["id"] == "abduction"
    assert client.post("/api/exercise", json={"id": "nope"}).status_code == 400
    assert client.post("/api/target", json={"target": 140}).json()["ok"]
    assert pipeline.coach.target == 140
    assert client.post("/api/target", json={"target": 500}).status_code == 400
    assert len(client.get("/api/exercises").json()) == 3


def test_api_pause_blocks_coach(pipeline):
    client = TestClient(create_app(pipeline, {}))
    assert client.post("/api/coach/pause", json={"paused": True}).json() == {"ok": True, "paused": True}
    pipeline._process(pipeline.source.latest())
    _, state = pipeline.latest_state()
    assert state["coach"]["state"] == "paused" and state["coach"]["user_paused"] is True
    assert client.post("/api/coach/pause", json={"paused": False}).json()["paused"] is False
    assert pipeline.coach.user_paused is False


def test_api_status_side_and_ws(pipeline):
    app = create_app(pipeline, {"session": "test"})
    client = TestClient(app)
    assert client.get("/api/status").json()["session"] == "test"
    assert client.post("/api/side", json={"side": "left"}).json()["side"] == "left"
    assert client.post("/api/side", json={"side": "middle"}).status_code == 400
    with client.websocket_connect("/ws/live") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "camera"


def test_recording_off_without_dataset_dir_writes_nothing(pipeline):
    """No --dataset-dir: refuse record, and do not create anything under ml/data/real."""
    from physiobuddy_hub.pipeline import RECORDING_OFF_REASON
    from physiobuddy_hub.recorder import DEFAULT_ROOT

    assert pipeline.recorder is None
    before = set(DEFAULT_ROOT.iterdir()) if DEFAULT_ROOT.exists() else None
    client = TestClient(create_app(pipeline, {}))
    status = client.get("/api/record/status")
    assert status.status_code == 200
    body = status.json()
    assert body["enabled"] is False and body["active"] is False
    assert body["reason"] == RECORDING_OFF_REASON
    start = client.post("/api/record/start", json={
        "subject_id": "S01", "side": "right", "consent": True, "protocol": "quick"})
    assert start.status_code == 409
    assert start.json() == {"ok": False, "enabled": False, "reason": RECORDING_OFF_REASON}
    for action in ("next", "prev", "stop"):
        step = client.post(f"/api/record/{action}")
        assert step.status_code == 409
        assert step.json() == {"ok": False, "enabled": False, "reason": RECORDING_OFF_REASON}
    after = set(DEFAULT_ROOT.iterdir()) if DEFAULT_ROOT.exists() else None
    assert before == after
    _, state = pipeline.latest_state()
    assert state["recorder"]["enabled"] is False


def test_recording_accepted_with_dataset_dir(pipeline, tmp_path):
    """--dataset-dir <tmp> accepts a consented recording and leaves ml/data/real alone."""
    from physiobuddy_hub.recorder import DEFAULT_ROOT, DatasetRecorder

    before = set(DEFAULT_ROOT.iterdir()) if DEFAULT_ROOT.exists() else None
    pipeline.recorder = DatasetRecorder(tmp_path, up_cam=pipeline.up_cam)
    client = TestClient(create_app(pipeline, {}))
    assert client.get("/api/record/status").json()["enabled"] is True
    start = client.post("/api/record/start", json={
        "subject_id": "S01", "side": "right", "consent": True, "protocol": "quick"})
    assert start.status_code == 200
    body = start.json()
    assert body["ok"] is True and body["active"] is True and body["enabled"] is True
    assert (tmp_path / "S01").is_dir()
    assert client.post("/api/record/stop").status_code == 200
    after = set(DEFAULT_ROOT.iterdir()) if DEFAULT_ROOT.exists() else None
    assert before == after


def test_rest_calibration_sets_shrug_baseline(pipeline):
    pipeline.start_rest_capture()
    for _ in range(20):
        pipeline._process(pipeline.source.latest())
    res = pipeline.rest_capture_result()
    assert res["ok"], res
    assert pipeline.kin.shrug_baseline == pytest.approx(res["shrug_baseline"], abs=1e-4)
