"""Webcam adapter. No camera and no Python 3.12: recorded worker lines only."""

import json
from pathlib import Path

import numpy as np
import pytest

from physiobuddy_hub.capture.auri_cv import (
    SETUP_HINT, WORLD_UP, adapt_line, auri_cv_python, landmark_hint,
)
from physiobuddy_hub.core.skeleton_kin import SkeletonKinematics
from physiobuddy_hub.datatypes import (
    L_ELBOW, L_HIP, L_SHOULDER, L_WRIST, R_ELBOW, R_HIP, R_SHOULDER, R_WRIST,
)

FIXTURE = Path(__file__).parent / "fixtures" / "auri_cv_frame.jsonl"


def _lines():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_fixture_maps_shoulders_elbows_wrists_and_hips():
    pose, skeleton, engine, frame = adapt_line(_lines()[0], host_rx_ms=1012.0)
    assert frame.intrinsics.width == 640 and frame.frame_number == 1
    assert skeleton is not None and pose is not None
    np.testing.assert_allclose(skeleton.points[R_SHOULDER], [0.18, -0.2, 1.5])
    np.testing.assert_allclose(skeleton.points[L_SHOULDER], [-0.18, -0.2, 1.5])
    np.testing.assert_allclose(skeleton.points[R_ELBOW], [0.18, 0.1, 1.5])
    np.testing.assert_allclose(skeleton.points[L_WRIST], [-0.18, 0.36, 1.5])
    np.testing.assert_allclose(skeleton.points[R_HIP], [0.1, 0.3, 1.5])
    np.testing.assert_allclose(skeleton.points[L_HIP], [-0.1, 0.3, 1.5])
    assert skeleton.valid[R_WRIST]
    assert engine["flexion_deg"] is None
    assert engine["abduction_deg"] is None
    assert engine["display_elevation_deg"] is None
    assert engine["compensation"] is None
    assert engine["latency_ms"] == 12.0
    angles = SkeletonKinematics("right").compute(skeleton, WORLD_UP)
    assert angles.elevation.value is not None and abs(angles.elevation.value) < 2.0


def test_low_visibility_elbow_makes_the_arm_unavailable():
    line = _lines()[0]
    for landmark in line["landmarks"]:
        if landmark["name"] == "RIGHT_ELBOW":
            landmark["vis"] = 0.2
    _pose, skeleton, _engine, _frame = adapt_line(line, host_rx_ms=line["t_ms"])
    assert skeleton is not None and not skeleton.valid[R_ELBOW]
    assert np.isnan(skeleton.points[R_ELBOW]).all()
    angles = SkeletonKinematics("right").compute(skeleton, WORLD_UP)
    assert angles.elevation.value is None
    assert angles.elbow_flexion.value is None
    assert skeleton.valid[L_ELBOW]


def test_captured_empty_room_line_stays_null():
    captured = _lines()[1]
    assert captured["w"] == 640 and captured["engine"]["quality"] == "UNAVAILABLE"
    assert all(lm["vis"] is None and lm["x"] is None for lm in captured["landmarks"])
    pose, skeleton, engine, frame = adapt_line(captured, host_rx_ms=captured["t_ms"] + 40)
    assert pose is None and skeleton is None
    assert frame.frame_number == captured["frame"]
    assert engine["elevation_deg"] is None
    assert engine["flexion_deg"] is None
    assert engine["abduction_deg"] is None
    assert engine["display_elevation_deg"] is None
    assert engine["filtered_elevation_deg"] is None
    assert engine["compensation"] is None
    assert engine["latency_ms"] == 40.0


def test_unavailable_or_armless_frame_derives_nothing():
    from physiobuddy_hub.pipeline import CameraPipeline

    torso = [
        {"name": "NOSE", "u": 320.0, "v": 80.0, "vis": 0.95, "x": 0.0, "y": -0.5, "z": 1.4},
        {"name": "LEFT_EAR", "u": 250.0, "v": 90.0, "vis": 0.95, "x": -0.12, "y": -0.48, "z": 1.4},
        {"name": "RIGHT_EAR", "u": 390.0, "v": 90.0, "vis": 0.95, "x": 0.12, "y": -0.48, "z": 1.4},
        {"name": "LEFT_SHOULDER", "u": 220.0, "v": 160.0, "vis": 0.95, "x": -0.18, "y": -0.2, "z": 1.5},
        {"name": "RIGHT_SHOULDER", "u": 420.0, "v": 160.0, "vis": 0.95, "x": 0.18, "y": -0.2, "z": 1.5},
    ]
    cases = (
        ("UNAVAILABLE", torso),
        ("VALID", torso),
        ("UNAVAILABLE", _lines()[0]["landmarks"]),
    )
    for quality, landmarks in cases:
        line = {
            "t_ms": 2000.0, "frame": 9, "w": 640, "h": 480,
            "landmarks": landmarks,
            "engine": {"quality": quality, "elevation_deg": None, "flexion_deg": None,
                       "abduction_deg": None, "display_elevation_deg": None,
                       "filtered_elevation_deg": None, "compensation": None, "rep_count": 0},
        }
        pose, skeleton, engine, frame = adapt_line(line, host_rx_ms=2040.0)
        assert skeleton is None
        assert engine["elevation_deg"] is None

        class Source:
            def posed_skeleton(self):
                return pose, skeleton

            def engine_view(self):
                return engine

        class Pose:
            name = "must-not-run"

            def __call__(self, _bgr):
                raise AssertionError("depth lift path ran")

        pipeline = CameraPipeline(Source(), Pose(), up_cam=WORLD_UP.copy(), side="right")
        pipeline._process(frame)
        _version, state = pipeline.latest_state()
        assert state["angles"] is None


def test_empty_room_keeps_engine_nulls_and_no_skeleton():
    line = {
        "t_ms": 50.0, "frame": 3, "w": 640, "h": 480,
        "landmarks": [{"i": 8, "name": "RIGHT_ELBOW", "u": None, "v": None, "vis": None,
                       "x": None, "y": None, "z": None}],
        "engine": {"quality": "UNAVAILABLE", "elevation_deg": None, "flexion_deg": None,
                   "abduction_deg": None, "filtered_elevation_deg": None,
                   "display_elevation_deg": None, "compensation": None, "rep_count": 0},
    }
    pose, skeleton, engine, _frame = adapt_line(line, host_rx_ms=70.0)
    assert pose is None and skeleton is None
    assert engine["quality"] == "UNAVAILABLE"
    assert engine["elevation_deg"] is None
    assert engine["display_elevation_deg"] is None
    assert engine["rep_count"] == 0


def test_pipeline_reads_the_worker_skeleton_and_skips_depth_lift():
    from physiobuddy_hub.pipeline import CameraPipeline

    pose, skeleton, engine, frame = adapt_line(_lines()[0], host_rx_ms=1012.0)

    class Source:
        def posed_skeleton(self):
            return pose, skeleton

        def engine_view(self):
            return engine

    class Pose:
        name = "must-not-run"

        def __call__(self, _bgr):
            raise AssertionError("depth lift path ran")

    pipeline = CameraPipeline(Source(), Pose(), up_cam=WORLD_UP.copy(), side="right")
    pipeline._process(frame)
    _version, state = pipeline.latest_state()
    assert state["auri_cv"]["quality"] == "VALID"
    assert state["auri_cv"]["flexion_deg"] is None
    assert state["angles"]["elevation"]["value"] is not None
    assert "straps" not in state


def test_missing_checkout_names_the_setup_commands(tmp_path):
    with pytest.raises(SystemExit) as caught:
        auri_cv_python(tmp_path)
    text = str(caught.value)
    assert text == SETUP_HINT
    assert "git clone https://github.com/abdulmueez3-14/AURIII external/AURIII" in text
    assert "uv venv external/AURIII/.venv --python 3.12" in text
    assert "uv pip install --native-tls -r external/AURIII/requirements.txt" in text


def test_partial_person_names_the_missing_landmarks_and_stays_unmeasured():
    assert landmark_hint([], []) is None
    assert landmark_hint(["LEFT_HIP", "RIGHT_HIP", "RIGHT_WRIST"], []) == (
        "Step back: hips and wrist must be visible")
    assert landmark_hint([], ["RIGHT_WRIST"]) == "Step back: wrist must be visible"
    line = {
        "t_ms": 10.0, "frame": 4, "w": 320, "h": 240,
        "landmarks": [
            {"name": "RIGHT_SHOULDER", "u": 200.0, "v": 80.0, "vis": 0.99, "x": 0.2, "y": -0.2, "z": 1.0},
            {"name": "RIGHT_ELBOW", "u": 210.0, "v": 140.0, "vis": 0.79, "x": 0.2, "y": 0.1, "z": 1.0},
        ],
        "engine": {"quality": "UNAVAILABLE", "elevation_deg": None, "flexion_deg": None,
                   "missing": ["LEFT_HIP", "RIGHT_HIP", "RIGHT_WRIST"], "low_confidence": []},
    }
    _pose, skeleton, engine, _frame = adapt_line(line, host_rx_ms=20.0)
    assert skeleton is None
    assert engine["elevation_deg"] is None
    assert engine["hint"] == "Step back: hips and wrist must be visible"


def test_webcam_cannot_combine_with_sim_or_a_bag():
    from physiobuddy_hub.__main__ import main

    with pytest.raises(SystemExit):
        main(["run", "--sim", "--webcam", "0"])
    with pytest.raises(SystemExit):
        main(["run", "--bag", "clip.bag", "--webcam"])
