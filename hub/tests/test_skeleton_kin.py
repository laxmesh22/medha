import numpy as np
import pytest

from conftest import make_skeleton, rot_x, rot_z
from physiobuddy_hub.core.skeleton_kin import SkeletonKinematics
from physiobuddy_hub.datatypes import L_HIP, L_SHOULDER, R_HIP, R_WRIST

S30, C30 = np.sin(np.radians(30)), np.cos(np.radians(30))


def kin(side="right"):
    return SkeletonKinematics(side)


def test_arm_at_side_is_rest_with_no_plane(up_cam):
    a = kin().compute(make_skeleton(), up_cam)
    assert a.elevation.value == pytest.approx(0, abs=1e-6)
    assert a.movement == "rest"
    assert a.plane_of_elevation.value is None  # unavailable, not 0
    assert a.plane_of_elevation.quality == "unavailable"


def test_flexion_90(up_cam):
    a = kin().compute(make_skeleton(right_u=(1, 0, 0), right_f=(1, 0, 0)), up_cam)
    assert a.elevation.value == pytest.approx(90, abs=1e-6)
    assert a.plane_of_elevation.value == pytest.approx(0, abs=1e-6)
    assert a.movement == "flexion"


def test_abduction_90_right(up_cam):
    a = kin().compute(make_skeleton(right_u=(0, 0, 1), right_f=(0, 0, 1)), up_cam)
    assert a.elevation.value == pytest.approx(90, abs=1e-6)
    assert a.plane_of_elevation.value == pytest.approx(90, abs=1e-6)
    assert a.movement == "abduction"


def test_abduction_left_side_is_mirrored(up_cam):
    a = kin("left").compute(make_skeleton(left_u=(0, 0, -1), left_f=(0, 0, -1)), up_cam)
    assert a.plane_of_elevation.value == pytest.approx(90, abs=1e-6)
    assert a.movement == "abduction"


def test_overhead_flexion_180(up_cam):
    a = kin().compute(make_skeleton(right_u=(0, 1, 0), right_f=(0, 1, 0)), up_cam)
    assert a.elevation.value == pytest.approx(180, abs=1e-4)


def test_extension(up_cam):
    a = kin().compute(make_skeleton(right_u=(-S30, -C30, 0), right_f=(-S30, -C30, 0)), up_cam)
    assert a.elevation.value == pytest.approx(30, abs=1e-6)
    assert a.movement == "extension"


@pytest.mark.parametrize("side,z", [("right", 1), ("left", -1)])
def test_external_rotation_positive_both_sides(up_cam, side, z):
    f = (C30, 0, z * S30)
    sk = make_skeleton(right_f=f) if side == "right" else make_skeleton(left_f=f)
    a = kin(side).compute(sk, up_cam)
    assert a.elbow_flexion.value == pytest.approx(90, abs=1e-6)
    assert a.rotation.value == pytest.approx(30, abs=1e-6)


def test_internal_rotation_negative(up_cam):
    a = kin().compute(make_skeleton(right_f=(C30, 0, -S30)), up_cam)
    assert a.rotation.value == pytest.approx(-30, abs=1e-6)


def test_rotation_unavailable_when_elbow_straight(up_cam):
    a = kin().compute(make_skeleton(), up_cam)  # forearm hanging, elbow 0 deg
    assert a.rotation.value is None
    assert "elbow" in a.rotation.reason


def test_rotation_unavailable_when_wrist_missing(up_cam):
    a = kin().compute(make_skeleton(right_f=(1, 0, 0), drop=(R_WRIST,)), up_cam)
    assert a.rotation.value is None
    assert a.rotation.quality == "unavailable"


def test_no_shoulders_gives_all_unavailable(up_cam):
    a = kin().compute(make_skeleton(drop=(L_SHOULDER,)), up_cam)
    assert "NO_THORAX" in a.flags
    assert all(m.value is None for m in (a.elevation, a.rotation, a.trunk_lean_sagittal))


def test_missing_hips_falls_back_to_gravity_with_low_quality(up_cam):
    a = kin().compute(make_skeleton(right_u=(1, 0, 0), drop=(L_HIP, R_HIP)), up_cam)
    assert a.elevation.value == pytest.approx(90, abs=1e-6)
    assert a.elevation.quality == "low"
    assert "THORAX_FROM_GRAVITY" in a.flags
    assert a.trunk_lean_sagittal.value is None


def test_forward_trunk_lean(up_cam):
    a = kin().compute(make_skeleton(trunk_R=rot_z(15)), up_cam)
    assert a.trunk_lean_sagittal.value == pytest.approx(15, abs=1e-6)
    assert a.trunk_lean_lateral.value == pytest.approx(0, abs=1e-6)


def test_lateral_lean_toward_affected_side_is_positive(up_cam):
    # positive rot_x tilts the trunk toward the patient's right
    a = kin("right").compute(make_skeleton(trunk_R=rot_x(12)), up_cam)
    assert a.trunk_lean_lateral.value == pytest.approx(12, abs=1e-6)
    a = kin("left").compute(make_skeleton(trunk_R=rot_x(12)), up_cam)
    assert a.trunk_lean_lateral.value == pytest.approx(-12, abs=1e-6)


def test_apparent_vs_true_gap_when_leaning_back(up_cam):
    # arm flexed 90 deg relative to thorax, trunk leaning back 20 deg -> apparent 110 deg
    a = kin().compute(make_skeleton(right_u=(1, 0, 0), trunk_R=rot_z(-20)), up_cam)
    assert a.elevation.value == pytest.approx(90, abs=1e-6)
    assert a.apparent_elevation.value == pytest.approx(110, abs=1e-6)
    assert "APPARENT_TRUE_GAP" in a.flags
    assert "TRUNK_LEAN_SAGITTAL" in a.flags


def test_shrug_flag_against_baseline(up_cam):
    k = kin()
    base = k.compute(make_skeleton(), up_cam).shrug_index.value
    k.set_shrug_baseline(base)
    assert "SHRUG" not in k.compute(make_skeleton(), up_cam).flags
    assert "SHRUG" in k.compute(make_skeleton(right_shoulder_raise=0.06), up_cam).flags


def test_camera_tilt_does_not_change_relative_angles():
    """Thorax-relative angles must not depend on how the camera is tilted."""
    a = SkeletonKinematics("right").compute(make_skeleton(right_u=(0, 0, 1)), np.array([0.0, -1.0, 0.0]))
    tilted_up = np.array([0.0, -np.cos(np.radians(8)), np.sin(np.radians(8))])
    b = SkeletonKinematics("right").compute(make_skeleton(right_u=(0, 0, 1)), tilted_up)
    assert a.elevation.value == pytest.approx(b.elevation.value, abs=1e-6)
    assert a.plane_of_elevation.value == pytest.approx(b.plane_of_elevation.value, abs=1e-6)
