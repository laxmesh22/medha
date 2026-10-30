import numpy as np
import pytest

from physiobuddy_hub.datatypes import (
    L_EAR, L_ELBOW, L_HIP, L_SHOULDER, L_WRIST, NOSE, NUM_KEYPOINTS, R_EAR, R_ELBOW, R_HIP,
    R_SHOULDER, R_WRIST, Skeleton3D,
)

BODY_DISTANCE_M = 2.2


def body_to_cam(v, origin=np.array([0.0, 0.0, BODY_DISTANCE_M])):
    """Thorax frame (X anterior, Y up, Z right) of a patient facing the camera -> RealSense frame."""
    v = np.asarray(v, dtype=float)
    return np.array([-v[2], -v[1], -v[0]]) + origin


def rot_z(deg):
    """Rotation about the body Z (right) axis: positive tilts Y (up) toward X (anterior)."""
    a = np.radians(deg)
    return np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1]])


def rot_x(deg):
    """Rotation about the body X (anterior) axis: positive tilts Y (up) toward Z (right)."""
    a = np.radians(deg)
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def make_skeleton(right_u=(0, -1, 0), right_f=(0, -1, 0), left_u=(0, -1, 0), left_f=(0, -1, 0),
                  trunk_R=np.eye(3), right_shoulder_raise=0.0, drop=()):
    """Build a Skeleton3D in camera coordinates. Arm directions are given in the *thorax* frame."""
    pts = {
        R_SHOULDER: np.array([0, right_shoulder_raise, 0.18]),
        L_SHOULDER: np.array([0, 0, -0.18]),
        R_HIP: np.array([0, -0.5, 0.12]),
        L_HIP: np.array([0, -0.5, -0.12]),
        R_EAR: np.array([0, 0.22, 0.08]),
        L_EAR: np.array([0, 0.22, -0.08]),
        NOSE: np.array([0.1, 0.2, 0.0]),
    }
    pts[R_ELBOW] = pts[R_SHOULDER] + 0.30 * np.asarray(right_u, float)
    pts[R_WRIST] = pts[R_ELBOW] + 0.25 * np.asarray(right_f, float)
    pts[L_ELBOW] = pts[L_SHOULDER] + 0.30 * np.asarray(left_u, float)
    pts[L_WRIST] = pts[L_ELBOW] + 0.25 * np.asarray(left_f, float)

    points = np.full((NUM_KEYPOINTS, 3), np.nan)
    valid = np.zeros(NUM_KEYPOINTS, dtype=bool)
    for i, p in pts.items():
        if i in drop:
            continue
        points[i] = body_to_cam(trunk_R @ p)
        valid[i] = True
    return Skeleton3D(points=points, valid=valid, body_depth_m=BODY_DISTANCE_M)


UP_CAM = np.array([0.0, -1.0, 0.0])


@pytest.fixture(autouse=True)
def scratch_worn_mount(tmp_path, monkeypatch):
    """Tests never read or overwrite the station's saved strap position."""
    from physiobuddy_hub.straps import calibrate
    monkeypatch.setattr(calibrate, "MOUNT_FILE", tmp_path / "straps_mount.local.json")


@pytest.fixture
def up_cam():
    return UP_CAM.copy()
