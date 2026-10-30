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


def test_raise_direction_sets_forward_when_the_box_is_twisted():
    """A 90 deg twist on the strap used to turn a forward raise into a side raise."""
    side, spin = "right", {"upper_arm": 90.0, "forearm": 90.0}
    cal = npose(side, spin, seed=3)
    rows = {s: [] for s in SENSORS}
    for deg in range(20, 85, 5):
        R = axis_angle(EZ, np.radians(deg))
        q = wear({"trunk": np.eye(3), "upper_arm": R, "forearm": R}, side, spin, seed=3)
        for s in SENSORS:
            rows[s].append((q[s].tolist(), None))
    done = cal.refine_from_raise_direction(rows)
    assert "upper_arm" in done and "forearm" in done
    posed = wear({"trunk": np.eye(3), "upper_arm": axis_angle(EZ, np.radians(70)),
                  "forearm": axis_angle(EZ, np.radians(70))}, side, spin, seed=3)
    a = StrapKinematics(cal).compute(posed)
    assert a.movement == "flexion" and abs(a.plane_of_elevation.value) < 12
    side_pose = wear({"trunk": np.eye(3),
                      "upper_arm": axis_angle([1.0, 0, 0], np.radians(-70)),
                      "forearm": axis_angle([1.0, 0, 0], np.radians(-70))}, side, spin, seed=3)
    b = StrapKinematics(cal).compute(side_pose)
    assert b.movement == "abduction"


def test_waist_lean_sets_forward_when_the_box_is_on_the_back_or_side():
    """The N-pose cannot see which way the waist box faces. A forward lean read backward or sideways."""
    from physiobuddy_hub.straps.calibrate import strap_pose

    for spin_deg in (180.0, 90.0, -135.0):
        spin = {"trunk": spin_deg}
        cal = npose("right", spin, seed=6)
        bow = axis_angle(EZ, np.radians(-20))                       # trunk tipped 20 deg forward
        posed = wear({"trunk": bow, "upper_arm": bow, "forearm": bow}, "right", spin, seed=6)
        before = StrapKinematics(cal).compute(posed)
        assert abs(before.trunk_lean_sagittal.value - 20) > 10
        rows = {s: [] for s in SENSORS}
        for deg in range(4, 32, 2):
            q = wear({s: axis_angle(EZ, np.radians(-deg)) for s in SENSORS}, "right", spin, seed=6)
            for s in SENSORS:
                rows[s].append((q[s].tolist(), None))
        assert cal.refine_trunk_from_lean(rows) and cal.forward_raise["trunk"]
        after = StrapKinematics(cal).compute(posed)
        assert abs(after.trunk_lean_sagittal.value - 20) < 1 and abs(after.trunk_lean_lateral.value) < 1
        snap = {"trunk": {"available": True, "quat": posed["trunk"].tolist()}}
        assert strap_pose(cal, snap)["trunk"][2] > 0.3              # chest tips toward the camera


def test_waist_lean_is_rejected_when_the_trunk_stays_upright():
    cal = npose("right", seed=6)
    still = wear({s: np.eye(3) for s in SENSORS}, "right", seed=6)
    rows = {"trunk": [(still["trunk"].tolist(), None)] * 20}
    assert not cal.refine_trunk_from_lean(rows) and "trunk" not in cal.forward_raise


def test_straight_arm_raise_fixes_a_forearm_calibrated_with_a_bent_elbow():
    """Live: the forearm sat 30-50 deg off the upper arm with the elbow straight."""
    from physiobuddy_hub.straps.calibrate import strap_pose

    side, spin = "right", {"forearm": 70.0, "upper_arm": -30.0}
    bent = axis_angle(EZ, np.radians(20))                           # forearm 20 deg forward during the N-pose
    q = wear({"upper_arm": np.eye(3), "forearm": bent}, side, spin, seed=8)
    cal = StrapCalibration.from_npose(side, {s: [q[s]] * 5 for s in q})
    rows = {s: [] for s in SENSORS}
    for d in range(0, 120, 3):
        R = axis_angle(EZ, np.radians(d))                           # slow straight-arm forward raise
        q = wear({"upper_arm": R, "forearm": R}, side, spin, seed=8)
        for s in q:
            rows[s].append((q[s].tolist(), None))
    cal.refine_from_raise_direction(rows)

    def elbow(segs):
        q = wear(segs, side, spin, seed=8)
        p = strap_pose(cal, {s: {"available": True, "quat": q[s].tolist()} for s in q})
        return np.degrees(np.arccos(np.clip(np.dot(p["upper_arm"], p["forearm"]), -1, 1))), p

    side_raise = axis_angle([1.0, 0, 0], np.radians(-90))
    before, _ = elbow({"upper_arm": side_raise, "forearm": side_raise})
    err = cal.align_forearm_to_upper_arm(rows)
    assert err is not None and err < 1.0
    after, p = elbow({"upper_arm": side_raise, "forearm": side_raise})
    assert before > 10 and after < 2 and p["forearm"][0] < -0.95     # straight arm out to the patient's right
    bend, p = elbow({"upper_arm": np.eye(3), "forearm": axis_angle(EZ, np.radians(90))})
    assert abs(bend - 90) < 2 and p["forearm"][2] > 0.95              # elbow 90, forearm toward the camera


def test_forearm_fit_is_refused_when_the_elbow_bends_during_the_raise():
    cal = npose("right", seed=8)
    rows = {s: [] for s in SENSORS}
    for d in range(0, 120, 3):
        q = wear({"upper_arm": axis_angle(EZ, np.radians(d)), "forearm": axis_angle(EZ, np.radians(min(2 * d, 150)))},
                 "right", seed=8)
        for s in q:
            rows[s].append((q[s].tolist(), None))
    before = cal.mount["forearm"].copy()
    assert cal.align_forearm_to_upper_arm(rows) is None and np.allclose(cal.mount["forearm"], before)


def test_calibration_says_when_a_band_is_on_the_wrong_body_part():
    from physiobuddy_hub.straps.calibrate import placement_problem

    def capture(moving):
        rows = {s: [] for s in SENSORS}
        for deg in range(0, 90, 5):
            segs = {s: axis_angle(EZ, np.radians(deg if s in moving else 0)) for s in SENSORS}
            q = wear(segs, "right", seed=1)
            for s in SENSORS:
                rows[s].append((q[s].tolist(), None))
        return rows

    assert placement_problem("raise", capture({"upper_arm", "forearm"})) is None
    assert "upper-arm band" in placement_problem("raise", capture({"forearm"}))
    assert "swapped" in placement_problem("raise", capture({"trunk", "forearm"}))
    assert placement_problem("lean", capture({"trunk", "upper_arm", "forearm"})) is None
    assert "waist band did not tip" in placement_problem("lean", capture({"upper_arm"}))


def test_worn_position_is_the_zero_and_can_be_saved():
    """However the box sits, the pose it was worn in is standing still."""
    spin = {"upper_arm": 35.0}
    cal = npose("right", spin, seed=2)
    worn = wear({s: np.eye(3) for s in SENSORS}, "right", spin, seed=2)
    for name in SENSORS:
        assert np.allclose(cal.segment(name, worn[name]), np.eye(3), atol=1e-6)
    restored = StrapCalibration.from_dict(cal.to_dict())
    for name in SENSORS:
        assert np.allclose(restored.segment(name, worn[name]), np.eye(3), atol=1e-6)


def test_figure_stays_standing_and_a_forward_raise_points_at_the_camera():
    from physiobuddy_hub.straps.calibrate import strap_pose

    cal = npose("right", seed=5)
    still = wear({s: np.eye(3) for s in SENSORS}, "right", seed=5)
    snap = {s: {"available": True, "quat": still[s].tolist()} for s in SENSORS}
    pose = strap_pose(cal, snap)
    assert pose["trunk"][1] > 0.9 and pose["upper_arm"][1] < -0.9

    arm = axis_angle(EZ, np.radians(90))
    moved = wear({"trunk": np.eye(3), "upper_arm": arm, "forearm": arm}, "right", seed=5)
    # Waist sample missing: the stand is kept, and the raised arm still points toward the camera (+Z).
    snap = {s: {"available": True, "quat": moved[s].tolist()} for s in ("upper_arm", "forearm")}
    pose = strap_pose(cal, snap)
    assert pose["trunk"] is None and pose["upper_arm"][2] > 0.9 and pose["upper_arm"][1] < 0.2
    # A right side raise goes to the patient's right, display -x. Forward and right together keep it a rotation.
    side = axis_angle([1.0, 0, 0], np.radians(-90))
    moved = wear({"trunk": np.eye(3), "upper_arm": side, "forearm": side}, "right", seed=5)
    snap = {s: {"available": True, "quat": moved[s].tolist()} for s in SENSORS}
    assert strap_pose(cal, snap)["upper_arm"][0] < -0.9


def test_missing_strap_means_unavailable_not_zero():
    kin = StrapKinematics(npose("left"))
    q = wear({"upper_arm": np.eye(3), "forearm": np.eye(3)}, "left")
    a = kin.compute(q)                                              # no waist strap
    assert a.elevation.value is None and a.trunk_lean_sagittal.value is None and a.shrug_index.value is None
    assert a.apparent_elevation.value is not None                   # arm strap + gravity alone still works
