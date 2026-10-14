"""End to end without hardware: simulated patient -> 3D kinematics -> coach verdicts."""

import numpy as np

from physiobuddy_hub.core.coach import Coach
from physiobuddy_hub.core.skeleton_kin import SkeletonKinematics
from physiobuddy_hub.datatypes import Skeleton3D
from physiobuddy_hub.sim import sim_skeleton

UP = np.array([0.0, -1.0, 0.0])


def run(coach, t0, t1, fps=30):
    kin = SkeletonKinematics("right")
    snap = None
    for t in np.arange(t0, t1, 1 / fps):
        pts, vis = sim_skeleton(t)
        sk = Skeleton3D(points=np.where(vis[:, None], pts, np.nan), valid=vis, body_depth_m=2.2)
        snap = coach.update(t, kin.compute(sk, UP).to_dict())
    return snap


def test_held_flexion_rep_is_correct():
    snap = run(Coach("flexion"), 0.0, 11.5)
    assert snap["rep_count"] == 1
    rep = snap["reps"][0]
    assert rep["correct"], rep["issues"]
    assert 125 < rep["peak"] < 140


def test_abduction_with_trunk_lean_needs_fixing():
    snap = run(Coach("abduction"), 11.5, 23.0)
    assert snap["rep_count"] == 1
    rep = snap["reps"][0]
    assert not rep["correct"]
    assert any("sideways" in i or "fake range" in i for i in rep["issues"])


def test_flexion_exercise_rejects_the_abduction_rep():
    snap = run(Coach("flexion"), 11.5, 23.0)
    assert snap["rep_count"] == 0
    assert any(e["code"] == "REP_REJECTED" for e in snap["events"])
