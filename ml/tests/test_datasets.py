"""Offline fixture tests for the public-dataset adapters (no network)."""

import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pbml.data import G  # noqa: E402
from pbml.datasets import common, intellirehab, rehab24, sequence_angles, spar  # noqa: E402

KINECT_JOINTS = ["SpineBase", "SpineMid", "Neck", "Head", "ShoulderLeft", "ElbowLeft", "WristLeft", "HandLeft",
                 "ShoulderRight", "ElbowRight", "WristRight", "HandRight", "HipLeft", "KneeLeft", "AnkleLeft",
                 "FootLeft", "HipRight", "KneeRight", "AnkleRight", "FootRight", "SpineShoulder", "HandTipLeft",
                 "ThumbLeft", "HandTipRight", "ThumbRight"]


def body_points(right_u=(0, -1, 0), left_u=(0, -1, 0)):
    """Named joints in a thorax-like body frame (X anterior, Y up, Z right), metres."""
    sh_r, sh_l = np.array([0, 0, 0.18]), np.array([0, 0, -0.18])
    return {
        "head": np.array([0.05, 0.25, 0]), "sh_r": sh_r, "sh_l": sh_l,
        "el_r": sh_r + 0.3 * np.asarray(right_u, float), "el_l": sh_l + 0.3 * np.asarray(left_u, float),
        "wr_r": sh_r + 0.55 * np.asarray(right_u, float), "wr_l": sh_l + 0.55 * np.asarray(left_u, float),
        "hip_r": np.array([0, -0.5, 0.12]), "hip_l": np.array([0, -0.5, -0.12]),
        "kn_r": np.array([0, -0.95, 0.12]), "kn_l": np.array([0, -0.95, -0.12]),
        "an_r": np.array([0, -1.4, 0.12]), "an_l": np.array([0, -1.4, -0.12]),
    }


def body_to_cam(v, depth=2.2):
    """Patient facing a level RealSense: body (X ant, Y up, Z right) -> camera (X right, Y down, Z fwd)."""
    return np.array([-v[2], -v[1], depth - v[0]])


# ------------------------------------------------------------------------------------------- SPAR
def test_spar_file_units_label_and_resampling(tmp_path):
    f = tmp_path / "S3_E2_L.csv"
    rows = np.tile([[-1.0, 0.0, 0.0, 0.5, 0.0, 0.0]], (100, 1))
    np.savetxt(f, rows, delimiter=",", header="ax,ay,az,wx,wy,wz", comments="")
    seg = spar.load_file(f)
    assert seg.subject == "SPAR03" and seg.exercise == "flexion" and seg.side == "left"
    assert 195 <= len(seg.acc) <= 200                           # 50 Hz -> 100 Hz
    np.testing.assert_allclose(seg.acc[0], [-G, 0, 0], atol=1e-6)
    np.testing.assert_allclose(seg.gyro[0, 0], np.degrees(0.5), atol=1e-6)


def test_spar_label_map_covers_showcase_and_unknown():
    assert {spar.TO_CLASS[e] for e in spar.CODES} == {
        "pendulum", "abduction", "flexion", "internal_rotation", "external_rotation", "unknown"}
    assert len(spar.file_names()) == 280


# ------------------------------------------------------------------------------------- IntelliRehab
def kinect_line(frame, pts_rs):
    """One raw IntelliRehab line from named RealSense-frame joints."""
    name_map = {"Head": "head", "ShoulderLeft": "sh_l", "ShoulderRight": "sh_r", "ElbowLeft": "el_l",
                "ElbowRight": "el_r", "WristLeft": "wr_l", "WristRight": "wr_r", "HipLeft": "hip_l",
                "HipRight": "hip_r", "KneeLeft": "kn_l", "KneeRight": "kn_r", "AnkleLeft": "an_l",
                "AnkleRight": "an_r"}
    parts = [str(frame), "1", f"{frame * 33.3:.1f}"]
    for j in KINECT_JOINTS:
        if j in name_map:
            x, y, z = intellirehab.KINECT_TO_RS @ pts_rs[name_map[j]]  # its own inverse
            parts += [f"({j}", "Tracked", f"{x:.5f}", f"{y:.5f}", f"{z:.5f}", "100", "200)"]
        else:
            parts += [f"({j}", "NotTracked", "0", "0", "0", "0", "0)"]
    return ",".join(parts)


def test_intellirehab_parse_and_kinematics(tmp_path):
    lines = ["Version 1"]
    for i in range(10):
        body = body_points(right_u=(1, 0, 0))                     # right arm forward, horizontal
        lines.append(kinect_line(i, {k: body_to_cam(v) for k, v in body.items()}))
    f = tmp_path / "305_18_2_2_1_stand.txt"   # gesture 2 moves the anatomical right arm (see GESTURES)
    f.write_text("\n".join(lines))
    seq = intellirehab.load_file(f)
    assert seq.exercise == "flexion" and seq.side == "right" and seq.correct is True
    assert seq.subject == "IR305" and seq.meta["position"] == "stand" and len(seq) == 10
    assert np.isnan(seq.points[0, 3]).all()                      # no ears in Kinect
    ang = sequence_angles(seq)[0]
    assert ang.elevation.value == pytest.approx(90, abs=1) and ang.movement == "flexion"


def _elev_range(seq, side):
    a = sequence_angles(common.SkeletonSequence("x", "flexion", side, seq.points, 30.0, "t"))
    e = np.array([v.elevation.value for v in a if v.elevation.value is not None])
    return float(e.max() - e.min()) if len(e) else 0.0


@pytest.mark.skipif(not (common.PUBLIC_ROOT / "intellirehab" / "SkeletonData").exists(),
                    reason="IntelliRehabDS not downloaded (ml/fetch_public.py)")
def test_intellirehab_real_files_label_the_moving_arm():
    files = [f for f in intellirehab._raw_files(common.PUBLIC_ROOT / "intellirehab")
             if f.stem.split("_")[2] in "2345" and f.stem.split("_")[4] == "1"][:40]
    seqs = [s for s in map(intellirehab.load_file, files) if s is not None]
    other = {"right": "left", "left": "right"}
    ok = [_elev_range(s, s.side) > _elev_range(s, other[s.side]) for s in seqs]
    assert len(seqs) >= 20 and np.mean(ok) > 0.9


@pytest.mark.skipif(not (common.PUBLIC_ROOT / "rehab24" / "3d_joints" / "Ex1").exists(),
                    reason="REHAB24-6 not downloaded (ml/fetch_public.py)")
def test_rehab24_real_abduction_reaches_overhead():
    seqs = rehab24.load(exercises=(1,))[:20]
    assert seqs and all(_elev_range(s, "right") > 60 for s in seqs)


def test_intellirehab_unlabelled_and_bad_names(tmp_path):
    f = tmp_path / "1_1_7_1_3_chair.txt"
    f.write_text(kinect_line(0, {k: body_to_cam(v) for k, v in body_points().items()}))
    seq = intellirehab.load_file(f)
    assert seq.exercise == "unknown" and seq.correct is None
    assert intellirehab.load_file(tmp_path / "readme.txt") is None


# ---------------------------------------------------------------------------------------- REHAB24-6
def mocap_frame(right_u=(0, -1, 0)):
    """26 OptiTrack joints (world Y up). Subject faces world +X, right = +Z."""
    b = body_points(right_u=right_u)
    to_w = lambda v: np.array([v[0], v[1] + 1.4, v[2]]) + np.array([3.0, 0, -1.0])  # noqa: E731
    out = np.zeros((26, 4))
    out[:, 3] = 1
    for coco, j in rehab24.COCO_FROM_MOCAP.items():
        key = {0: "head", 5: "sh_l", 6: "sh_r", 7: "el_l", 8: "el_r", 9: "wr_l", 10: "wr_r", 11: "hip_l",
               12: "hip_r", 13: "kn_l", 14: "kn_r", 15: "an_l", 16: "an_r"}[coco]
        out[j, :3] = to_w(b[key])
    return out


def test_rehab24_virtual_camera_abduction_angle():
    world = rehab24.mocap_to_coco(mocap_frame(right_u=(0, 0, 1))[None])  # right arm out to the side
    cam = common.world_to_virtual_camera(world, rehab24.UP_WORLD, distance_m=2.3)
    seq = common.SkeletonSequence("p", "abduction", "right", cam, 30.0, "rehab24")
    ang = sequence_angles(seq)[0]
    assert ang.elevation.value == pytest.approx(90, abs=1) and ang.movement == "abduction"
    assert cam[0, 5, 2] == pytest.approx(2.3, abs=0.01)           # shoulders 2.3 m in front of camera
    assert cam[0, 6, 0] < cam[0, 5, 0]                            # patient's right is image left


def test_rehab24_load_segments_reps(tmp_path):
    (tmp_path / "3d_joints" / "Ex1").mkdir(parents=True)
    frames = np.stack([mocap_frame() for _ in range(60)])
    np.save(tmp_path / "3d_joints" / "Ex1" / "PM_000-30fps.npy", frames)
    hdr = ("video_id;repetition_number;exercise_id;person_id;first_frame;last_frame;cam17_orientation;"
           "mocap_erroneous;exercise_subtype;lights_on;extra_person_in_cam17;extra_person_in_cam18;correctness")
    (tmp_path / "Segmentation.csv").write_text("\n".join([
        hdr, "PM_000;1;1;3;5;29;front;0;right arm;1;0;0;1", "PM_000;2;1;3;30;55;front;0;right arm;1;0;0;0",
        "PM_000;3;1;3;30;55;front;1;right arm;1;0;0;1", "PM_009;1;4;3;0;20;front;0;left leg;1;0;0;1"]))
    seqs = rehab24.load(tmp_path)
    assert [len(s) for s in seqs] == [25, 26]                     # mocap error rep + other exercise skipped
    assert seqs[0].correct is True and seqs[1].correct is False
    assert seqs[0].subject == "R24P03" and seqs[0].exercise == "abduction"


def test_remote_zip_reads_member_by_range(monkeypatch):
    buf = io.BytesIO()
    arr = np.arange(24.0).reshape(2, 3, 4)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Ex1/", b"")
        npy = io.BytesIO()
        np.save(npy, arr)
        zf.writestr("Ex1/PM_000-30fps.npy", npy.getvalue())
    blob = buf.getvalue()
    monkeypatch.setattr(common, "http_range", lambda url, a, b, timeout_s=600: blob[a:b + 1])
    rz = common.RemoteZip("mem://", len(blob))
    assert "Ex1/PM_000-30fps.npy" in rz.entries
    np.testing.assert_array_equal(np.load(io.BytesIO(rz.read("Ex1/PM_000-30fps.npy"))), arr)
