import numpy as np
import pytest

from physiobuddy_hub.capture.lift import lift_pose, torso_depth
from physiobuddy_hub.datatypes import (
    Intrinsics, L_HIP, L_SHOULDER, L_WRIST, NUM_KEYPOINTS, Pose2D, R_HIP, R_SHOULDER, R_WRIST,
)

INTR = Intrinsics(848, 480, 425.0, 425.0, 424.0, 240.0)


def make_pose(score=0.9):
    kp = np.zeros((NUM_KEYPOINTS, 2))
    kp[:] = [424, 240]
    kp[L_SHOULDER] = [480, 200]
    kp[R_SHOULDER] = [370, 200]
    kp[L_HIP] = [460, 330]
    kp[R_HIP] = [390, 330]
    kp[R_WRIST] = [300, 300]
    kp[L_WRIST] = [560, 300]
    return Pose2D(kp, np.full(NUM_KEYPOINTS, score))


def depth_image(z=2.0):
    return np.full((INTR.height, INTR.width), z, dtype=np.float32)


def test_deprojection_matches_pinhole():
    pose = make_pose()
    sk = lift_pose(pose, depth_image(2.0), INTR)
    u, v = pose.keypoints_px[R_WRIST]
    assert sk.valid[R_WRIST]
    np.testing.assert_allclose(
        sk.points[R_WRIST], [(u - INTR.ppx) / INTR.fx * 2.0, (v - INTR.ppy) / INTR.fy * 2.0, 2.0])
    assert sk.body_depth_m == pytest.approx(2.0)


def test_low_confidence_keypoint_is_invalid_not_zero():
    pose = make_pose()
    pose.scores[R_WRIST] = 0.1
    sk = lift_pose(pose, depth_image(), INTR, min_score=0.4)
    assert not sk.valid[R_WRIST]
    assert np.isnan(sk.points[R_WRIST]).all()


def test_depth_hole_makes_keypoint_invalid():
    pose = make_pose()
    depth = depth_image()
    u, v = pose.keypoints_px[R_WRIST].astype(int)
    depth[v - 5: v + 6, u - 5: u + 6] = 0.0
    sk = lift_pose(pose, depth, INTR)
    assert not sk.valid[R_WRIST]


def test_background_depth_is_rejected():
    """Wrist keypoint landing on the wall 3 m behind the patient must not be used."""
    pose = make_pose()
    depth = depth_image(2.0)
    u, v = pose.keypoints_px[R_WRIST].astype(int)
    depth[v - 5: v + 6, u - 5: u + 6] = 5.0
    sk = lift_pose(pose, depth, INTR)
    assert not sk.valid[R_WRIST]


def test_arm_in_front_of_body_is_kept():
    pose = make_pose()
    depth = depth_image(2.0)
    u, v = pose.keypoints_px[R_WRIST].astype(int)
    depth[v - 5: v + 6, u - 5: u + 6] = 1.5  # hand reaching toward the camera
    sk = lift_pose(pose, depth, INTR)
    assert sk.valid[R_WRIST]
    assert sk.points[R_WRIST][2] == pytest.approx(1.5)


def test_partial_hole_uses_median_of_valid_pixels():
    pose = make_pose()
    depth = depth_image(2.0)
    u, v = pose.keypoints_px[R_WRIST].astype(int)
    depth[v - 3: v + 4, u - 3: u] = 0.0  # left part of the 7x7 patch missing
    sk = lift_pose(pose, depth, INTR)
    assert sk.valid[R_WRIST]
    assert sk.points[R_WRIST][2] == pytest.approx(2.0)


def test_torso_depth_none_without_shoulders():
    pose = make_pose()
    pose.scores[L_SHOULDER] = 0.0
    assert torso_depth(pose, depth_image(), min_score=0.5) is None
