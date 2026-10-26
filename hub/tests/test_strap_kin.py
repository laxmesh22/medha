"""Strap geometry: the three BNO085s give the same clinical angles and flags as the camera."""

import numpy as np

from physiobuddy_hub.core.strap_kin import (
    SENSORS, StrapCalibration, StrapKinematics, axis_angle, matrix_to_quat, nominal_mount, quat_to_matrix,
)

Y_UP_TO_Z_UP = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])
EZ = np.array([0, 0, 1.0])


def wear(segs: dict, side: str, spin_deg: dict = None, seed: int = 0) -> dict:
    """Segment -> body rotations -> sensor quaternions. Each sensor has its own yaw reference (fixed by ``seed``
    for a session: a sensor keeps its reference until it is power-cycled)."""
    rng = np.random.default_rng(seed)
    yaws = {s: axis_angle(EZ, rng.uniform(-np.pi, np.pi)) for s in SENSORS}
    out = {}
    for s, R in segs.items():
        E = axis_angle([0, 1.0, 0], np.radians((spin_deg or {}).get(s, 0.0)))
        A = nominal_mount(s, side) @ E.T
        out[s] = matrix_to_quat(yaws[s] @ Y_UP_TO_Z_UP @ R @ A.T)
    return out


def npose(side: str, spin_deg: dict = None, seed: int = 0) -> StrapCalibration:
    q = wear({s: np.eye(3) for s in SENSORS}, side, spin_deg, seed)
    return StrapCalibration.from_npose(side, {s: [q[s]] * 5 for s in SENSORS})


def test_mounts_are_rotations_and_quaternions_round_trip():
    for side in ("right", "left"):
        for s in SENSORS:
            A = nominal_mount(s, side)
            assert np.allclose(A @ A.T, np.eye(3)) and np.isclose(np.linalg.det(A), 1.0)
            assert np.allclose(quat_to_matrix(matrix_to_quat(A)), A)


def test_flexion_and_rotation_match_the_pose_whatever_the_yaw_references():
    for side in ("right", "left"):
        kin = StrapKinematics(npose(side, seed=5))
        arm = axis_angle(EZ, np.radians(90))                     # humerus raised forward to horizontal
        a = kin.compute(wear({"trunk": np.eye(3), "upper_arm": arm, "forearm": arm}, side, seed=5))
        assert abs(a.elevation.value - 90) < 1 and abs(a.plane_of_elevation.value) < 1 and a.movement == "flexion"
        assert abs(a.elbow_flexion.value) < 1 and not a.flags
        zs = 1 if side == "right" else -1
        fore = axis_angle([0, 1.0, 0], np.radians(-40 * zs)) @ axis_angle(EZ, np.radians(90))   # ER 40 deg, elbow 90
        a = kin.compute(wear({"trunk": np.eye(3), "upper_arm": axis_angle([0, 1.0, 0], np.radians(-40 * zs)),
                              "forearm": fore}, side, seed=5))
        assert abs(a.elbow_flexion.value - 90) < 1 and abs(a.rotation.value - 40) < 1


def test_trunk_lean_is_flagged_from_the_waist_strap():
    kin = StrapKinematics(npose("right", seed=2))
    lean = axis_angle([1.0, 0, 0], np.radians(15))                 # lateral tilt of the trunk
    a = kin.compute(wear({"trunk": lean, "upper_arm": lean, "forearm": lean}, "right", seed=2))
    assert abs(abs(a.trunk_lean_lateral.value) - 15) < 1 and "TRUNK_LEAN_LATERAL" in a.flags
    assert a.elevation.value < 2                                    # arm still at the side of the trunk


def test_forward_raise_calibration_removes_strap_spin():
    side, spin = "right", {"upper_arm": 20.0, "forearm": -20.0}
    pose = {"trunk": np.eye(3), "upper_arm": axis_angle([0, 1.0, 0], np.radians(-40)),
            "forearm": axis_angle([0, 1.0, 0], np.radians(-40)) @ axis_angle(EZ, np.radians(90))}
    cal = npose(side, spin, seed=4)
    before = StrapKinematics(cal).compute(wear(pose, side, spin, seed=4)).rotation.value
    # slow straight-arm raise: rotation about segment +Z, measured in pod axes
    gyro = {}
    for s in ("upper_arm", "forearm"):
        A = nominal_mount(s, side) @ axis_angle([0, 1.0, 0], np.radians(spin[s])).T
        gyro[s] = np.tile(A @ np.array([0, 0, 40.0]), (30, 1))
    cal.refine_with_forward_raise(gyro)
    after = StrapKinematics(cal).compute(wear(pose, side, spin, seed=4)).rotation.value
    assert abs(before - 40) > 10 and abs(after - 40) < 1 and cal.forward_raise["upper_arm"]


def test_missing_strap_means_unavailable_not_zero():
    kin = StrapKinematics(npose("left"))
    q = wear({"upper_arm": np.eye(3), "forearm": np.eye(3)}, "left")
    a = kin.compute(q)                                              # no waist strap
    assert a.elevation.value is None and a.trunk_lean_sagittal.value is None and a.shrug_index.value is None
    assert a.apparent_elevation.value is not None                   # arm strap + gravity alone still works
