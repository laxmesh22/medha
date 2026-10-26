"""Hybrid coaching with a fake PB-MotionNet: the network can veto or add flags, never measure or override safety."""

import numpy as np
from fastapi.testclient import TestClient

from physiobuddy_hub.api.server import create_app
from physiobuddy_hub.capture.realsense import DEFAULT_UP
from physiobuddy_hub.core.coach import Coach
from physiobuddy_hub.core.skeleton_kin import SkeletonKinematics
from physiobuddy_hub.datatypes import Skeleton3D
from physiobuddy_hub.ml.features import CLASSES, COMP_FLAGS, D_IN, PHASES, WINDOW
from physiobuddy_hub.ml.motionnet_infer import MotionNetRunner
from physiobuddy_hub.pipeline import CameraPipeline
from physiobuddy_hub.sim import sim_skeleton
from test_pipeline import FakePose, FakeSource

UP = np.array([0.0, -1.0, 0.0])


def fake_predict(cls="flexion", phase="raising", form=-3.0, comp=None):
    def fn(x):
        assert x.shape == (1, WINDOW, D_IN) and x.dtype == np.float32
        ex = np.full((1, len(CLASSES)), -4.0, np.float32)
        ex[0, CLASSES.index(cls)] = 6.0
        ph = np.zeros((1, WINDOW, len(PHASES)), np.float32)
        ph[0, :, PHASES.index(phase)] = 5.0
        c = np.full((1, len(COMP_FLAGS)), -5.0, np.float32)
        for k, v in (comp or {}).items():
            c[0, COMP_FLAGS.index(k)] = v
        return ex, ph, np.array([[form]], np.float32), c
    return fn


META = {"model_version": "test", "thresholds": {"energy": {"skeleton": 0.0, "imu": 0.0, "fused": 0.0},
                                                "unknown_prob": 0.5, "comp_prob": 0.7, "autodetect_conf": 0.8}}


def nn_from(cls="flexion", phase="raising", comp=None, can_veto=True):
    return {"can_veto": can_veto,
            "predicted_exercise": cls, "is_unknown": cls == "unknown", "confidence": 0.95, "phase": phase,
            "form_score": 0.1, "comp_probs": {c: (comp or {}).get(c, 0.0) for c in COMP_FLAGS},
            "comp_threshold": 0.7}


def run(coach, t0, t1, nn=None, pause_at=None, fps=30):
    kin, snap = SkeletonKinematics("right"), None
    for t in np.arange(t0, t1, 1 / fps):
        if pause_at is not None and t >= pause_at and not coach.user_paused:
            coach.set_paused(True)
        pts, vis = sim_skeleton(t)
        sk = Skeleton3D(points=np.where(vis[:, None], pts, np.nan), valid=vis, body_depth_m=2.2)
        snap = coach.update(t, kin.compute(sk, UP).to_dict(), nn=nn(t) if callable(nn) else nn)
    return snap


def test_runner_without_model_is_unavailable(tmp_path):
    r = MotionNetRunner.from_dir(tmp_path)
    assert not r.available
    pts, vis = sim_skeleton(1.0)
    assert r.push(Skeleton3D(points=pts, valid=vis, body_depth_m=2.2), None, "right", UP) is None


def test_runner_known_and_unknown():
    kin = SkeletonKinematics("right")
    for cls, unknown in (("flexion", False), ("unknown", True)):
        r = MotionNetRunner(fake_predict(cls, comp={"SHRUG": 3.0}), META)
        out = None
        for t in np.arange(0, 2.5, 1 / 30):
            pts, vis = sim_skeleton(t)
            sk = Skeleton3D(points=np.where(vis[:, None], pts, np.nan), valid=vis, body_depth_m=2.2)
            out = r.push(sk, kin.compute(sk, UP).to_dict(), "right", UP)
        assert out["mode"] == "skeleton"
        assert out["is_unknown"] is unknown
        assert out["predicted_exercise"] == ("unknown" if unknown else "flexion")
        assert out["phase"] == "raising" and out["comp_probs"]["SHRUG"] > 0.9
    # energy above the calibrated threshold -> unknown even when argmax is a known class
    r = MotionNetRunner(fake_predict("flexion"), {"thresholds": {"energy": {"skeleton": -100.0}}})
    pts, vis = sim_skeleton(1.0)
    sk = Skeleton3D(points=pts, valid=vis, body_depth_m=2.2)
    for _ in range(WINDOW):
        out = r.push(sk, None, "right", UP)
    assert out["is_unknown"]


def test_no_network_keeps_rules_verdict():
    snap = run(Coach("flexion"), 0.0, 11.5, nn=None)
    assert snap["rep_count"] == 1 and snap["reps"][0]["correct"] and snap["nn"] is None


def test_network_unknown_vetoes_rep():
    snap = run(Coach("flexion"), 0.0, 11.5, nn=nn_from("unknown"))
    assert snap["rep_count"] == 0
    assert any(e["code"] == "REP_NN_UNKNOWN" for e in snap["events"])


def test_network_must_see_a_raise():
    snap = run(Coach("flexion"), 0.0, 11.5, nn=nn_from("flexion", phase="rest"))
    assert snap["rep_count"] == 0
    assert any(e["code"] == "REP_NN_PHASE" for e in snap["events"])


def test_network_comp_flag_adds_issue_but_not_short_rom():
    snap = run(Coach("flexion"), 0.0, 11.5, nn=nn_from("flexion", comp={"SHRUG": 0.9, "SHORT_ROM": 0.99,
                                                                        "ELBOW_DRIFT": 0.95}))
    rep = snap["reps"][0]
    assert snap["rep_count"] == 1 and not rep["correct"]
    assert rep["nn_flags"] == ["SHRUG"]          # ELBOW_DRIFT is not watched for flexion
    assert any("shrug" in i for i in rep["issues"])
    assert snap["nn"]["predicted_exercise"] == "flexion"


def test_unvalidated_network_is_advisory_only():
    for nn in (nn_from("unknown", can_veto=False), nn_from("flexion", phase="rest", can_veto=False),
               nn_from("flexion", comp={"SHRUG": 0.99}, can_veto=False)):
        snap = run(Coach("flexion"), 0.0, 11.5, nn=nn)
        assert snap["rep_count"] == 1 and snap["reps"][0]["correct"] and snap["reps"][0]["nn_flags"] == []
        assert snap["nn"]["can_veto"] is False          # still displayed


def test_runner_validation_must_match_model_version():
    ok = {"model_version": "v1", "real_validation": {"passed": True, "model_version": "v1"}}
    assert MotionNetRunner(fake_predict(), ok).validated
    assert not MotionNetRunner(fake_predict(), ok).imu_validated
    assert not MotionNetRunner(fake_predict(), {**ok, "model_version": "v2"}).validated
    assert not MotionNetRunner(fake_predict(), {"model_version": "v1", "real_validation": {"passed": False}}).validated
    assert not MotionNetRunner(fake_predict(), META).validated
    pts, vis = sim_skeleton(1.0)
    r = MotionNetRunner(fake_predict(), META)
    for _ in range(WINDOW):
        out = r.push(Skeleton3D(points=pts, valid=vis, body_depth_m=2.2), None, "right", UP,
                     imu={"gyro": {"forearm": np.zeros(3)}, "up": {"forearm": np.array([0.0, 1.0, 0.0])}})
    assert out["can_veto"] is False and out["mode"] == "skeleton"   # strap input ignored until validated


def test_network_cannot_override_safety_pause():
    snap = run(Coach("flexion"), 0.0, 11.5, nn=nn_from("flexion"), pause_at=3.0)
    assert snap["rep_count"] == 0 and snap["state"] == "paused"


class FakeRunner:
    available, autodetect_conf = True, 0.8

    def __init__(self, cls, validated=True):
        self.cls, self.validated = cls, validated

    def reset(self):
        pass

    def push(self, *a, **k):
        return nn_from(self.cls, phase="rest", can_veto=self.validated)


def test_autodetect_switches_exercise_while_resting():
    p = CameraPipeline(FakeSource(), FakePose(), up_cam=DEFAULT_UP, side="right", motionnet=FakeRunner("abduction"))
    p.source.latest = _clock(p.source.latest)
    for _ in range(60):                       # 2 s, autodetect off
        p._process(p.source.latest())
    assert p.coach.ex.id == "flexion"
    client = TestClient(create_app(p, {}))
    assert client.post("/api/autodetect", json={"enabled": True}).json() == {"ok": True, "enabled": True,
                                                                             "available": True}
    for _ in range(30):                       # 1 s: not yet
        p._process(p.source.latest())
    assert p.coach.ex.id == "flexion"
    for _ in range(30):
        p._process(p.source.latest())
    _, state = p.latest_state()
    assert p.coach.ex.id == "abduction"
    assert any(e["code"] == "AUTO_EXERCISE" for e in p.coach.events)
    assert state["autodetect"]["enabled"] and state["coach"]["nn"]["predicted_exercise"] == "abduction"


def test_autodetect_unavailable_without_model_or_validation():
    p = CameraPipeline(FakeSource(), FakePose(), up_cam=DEFAULT_UP, side="right")
    assert p.set_autodetect(True) == {"enabled": False, "available": False}
    p = CameraPipeline(FakeSource(), FakePose(), up_cam=DEFAULT_UP, side="right",
                       motionnet=FakeRunner("abduction", validated=False))
    assert p.set_autodetect(True) == {"enabled": False, "available": False}
    p.autodetect = True                      # even if forced on, advisory output never switches
    p.source.latest = _clock(p.source.latest)
    for _ in range(120):
        p._process(p.source.latest())
    assert p.coach.ex.id == "flexion"
    _, state = p.latest_state()
    assert state["autodetect"]["model_loaded"] and state["coach"]["nn"]["predicted_exercise"] == "abduction"


def _clock(latest, fps=30):
    """FakeSource advances 1 ms per frame; make it 30 fps so time-based gates are exercised."""
    n = [0]

    def f(timeout=1.0):
        fr = latest(timeout)
        n[0] += 1
        fr.timestamp_ms = 1000.0 + n[0] * 1000.0 / fps
        return fr
    return f
