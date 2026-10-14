import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pbml import augment  # noqa: E402
from pbml.data import synthetic_dataset  # noqa: E402
from pbml.datasets.common import DEFAULT_UP_CAM, SkeletonSequence, sequence_angles  # noqa: E402
from pbml.features_multimodal import (  # noqa: E402
    CLASSES, D_IN, D_SKEL, PHASES, WINDOW, from_imu_segment, from_skeleton_sequence, phase_labels,
    skeleton_sequence_features, windows,
)
from test_datasets import body_points, body_to_cam  # noqa: E402

COCO = {"head": 0, "sh_l": 5, "sh_r": 6, "el_l": 7, "el_r": 8, "wr_l": 9, "wr_r": 10, "hip_l": 11, "hip_r": 12,
        "kn_l": 13, "kn_r": 14, "an_l": 15, "an_r": 16}


def frame(right_u=(0, -1, 0), left_u=(0, -1, 0)):
    p = np.full((17, 3), np.nan)
    for k, v in body_points(right_u, left_u).items():
        p[COCO[k]] = body_to_cam(v)
    p[3], p[4] = body_to_cam(np.array([0, 0.22, -0.08])), body_to_cam(np.array([0, 0.22, 0.08]))
    return p


def arm_dir(elev_deg, plane="flexion"):
    a = np.radians(elev_deg)
    return (np.sin(a), -np.cos(a), 0) if plane == "flexion" else (0, -np.cos(a), np.sin(a))


def flexion_rep(peak=150.0, n=90):
    e = peak * np.sin(np.linspace(0, np.pi, n)) ** 2
    return np.stack([frame(right_u=arm_dir(v)) for v in e]), e


def test_feature_dims_and_mask():
    pts, _ = flexion_rep(n=20)
    x, angs = skeleton_sequence_features(pts, "right")
    assert x.shape == (20, D_IN)
    assert np.all(x[:, -2] == 1) and np.all(x[:, -1] == 0)          # skeleton valid, no IMU
    assert np.all(x[:, D_SKEL:D_SKEL + 18] == 0)


def test_left_patient_mirrors_to_same_features():
    """A left-arm flexion must look like a right-arm flexion to the network."""
    r = np.stack([frame(right_u=arm_dir(90))])
    l_ = np.stack([frame(left_u=arm_dir(90))])
    xr, _ = skeleton_sequence_features(r, "right")
    xl, _ = skeleton_sequence_features(l_, "left")
    np.testing.assert_allclose(xr, xl, atol=1e-5)


def test_missing_skeleton_is_zero_and_flagged():
    pts = np.full((3, 17, 3), np.nan)
    x, _ = skeleton_sequence_features(pts, "right")
    assert np.all(x == 0)


def test_restrict_rom_scales_elevation_keeps_plane():
    pts, e = flexion_rep(150, 30)
    seq = SkeletonSequence("s", "flexion", "right", augment.restrict_rom(pts, "right", 0.6, DEFAULT_UP_CAM),
                           30.0, "t")
    got = np.array([a.elevation.value for a in sequence_angles(seq)])
    np.testing.assert_allclose(got, 0.6 * e, atol=1.0)
    moving = [a for a, v in zip(sequence_angles(seq), e) if v > 40]
    assert all(a.movement == "flexion" for a in moving)


def test_viewpoint_preserves_true_angles():
    pts, e = flexion_rep(120, 20)
    out, up = augment.viewpoint(pts, DEFAULT_UP_CAM, yaw_deg=18, tilt_deg=7)
    seq = SkeletonSequence("s", "flexion", "right", out, 30.0, "t", up_cam=up)
    got = np.array([a.elevation.value for a in sequence_angles(seq)])
    np.testing.assert_allclose(got, e, atol=1.0)


def test_time_warp_length_and_nan_propagation():
    pts, _ = flexion_rep(n=40)
    pts[10:15, 8] = np.nan
    out = augment.time_warp(pts, 1.5)
    assert len(out) == 60 and np.isnan(out[:, 8]).any() and not np.isnan(out[:, 6]).any()


def test_random_chain_runs_and_occludes():
    rng = np.random.default_rng(0)
    pts, _ = flexion_rep(n=60)
    out, up, alpha = augment.random_skeleton_aug(pts, "right", DEFAULT_UP_CAM, rng)
    assert out.shape[1:] == (17, 3) and 0.45 <= alpha <= 1.0 and np.linalg.norm(up) == pytest.approx(1)


def test_phase_labels_follow_rep():
    e = np.concatenate([np.full(20, 5.0), np.linspace(5, 120, 40), np.full(60, 120.0), np.linspace(120, 5, 40),
                        np.full(20, 5.0)])
    lab = phase_labels(e)
    seen = [PHASES[lab[0]]]
    for v in lab[1:]:
        if PHASES[v] != seen[-1]:
            seen.append(PHASES[v])
    assert seen == ["rest", "raising", "hold", "lowering", "rest"]


def test_sample_from_sequence_and_windows():
    pts, _ = flexion_rep(n=100)
    s = from_skeleton_sequence(SkeletonSequence("s1", "flexion", "right", pts, 30.0, "t", correct=True))
    assert s.exercise == CLASSES.index("flexion") and s.correct == 1 and len(s.phase) == 100
    w = windows(s.x)
    assert w.shape == (3, WINDOW, D_IN)
    assert windows(s.x[:10]).shape == (1, WINDOW, D_IN)


def test_imu_segment_to_sample():
    seg = synthetic_dataset(n_subjects=1, reps_per_exercise=1, exercises=("er_band",))[0]
    seg.exercise = "external_rotation"
    s = from_imu_segment(seg)
    assert s.exercise == CLASSES.index("external_rotation")
    assert np.all(s.x[:, -1] == 1) and np.all(s.x[:, -2] == 0)
    assert abs(len(s.x) - len(seg.acc) * 0.3) <= 2
