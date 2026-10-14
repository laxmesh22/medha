import numpy as np
import pytest

from physiobuddy_hub.core.coach import HOLD, LOWERING, PAUSED, RAISING, REST, Coach

FPS = 30.0


def angles(elev, flags=(), movement="flexion", rotation=None):
    return {
        "movement": movement,
        "elevation": {"value": elev, "quality": "good", "reason": None},
        "rotation": {"value": rotation, "quality": "good" if rotation is not None else "unavailable",
                     "reason": None if rotation is not None else "rotation needs elbow at side"},
        "flags": list(flags),
    }


def run(coach, values, t0=0.0, flags=()):
    out = None
    for i, v in enumerate(values):
        out = coach.update(t0 + i / FPS, angles(v, flags))
    return out, t0 + len(values) / FPS


def rep_profile(peak=130.0, hold_s=5.5):
    up = np.linspace(5, peak, int(2.0 * FPS))
    hold = np.full(int(hold_s * FPS), peak)
    down = np.linspace(peak, 5, int(2.0 * FPS))
    rest = np.full(int(1.0 * FPS), 5.0)
    return np.concatenate([up, hold, down, rest])


def test_full_rep_counts_with_peak_and_hold():
    c = Coach("flexion")
    snap, _ = run(c, rep_profile(130, 5.5))
    assert snap["rep_count"] == 1
    rep = snap["reps"][0]
    assert rep["peak"] == pytest.approx(130, abs=0.5)
    assert rep["hold_s"] == pytest.approx(5.5, abs=0.8)
    assert rep["reached_target"] is True
    assert snap["state"] == REST
    assert rep["correct"] is True and snap["correct_count"] == 1
    assert any(e["code"] == "REP_GOOD" for e in snap["events"])


def test_short_hold_is_a_rep_that_needs_fixing():
    c = Coach("flexion")
    snap, _ = run(c, rep_profile(130, 1.5))
    rep = snap["reps"][0]
    assert snap["rep_count"] == 1 and snap["correct_count"] == 0
    assert rep["correct"] is False and "held" in rep["issues"][0]
    assert any(e["code"] == "REP_FIX" for e in snap["events"])


def test_live_form_verdict():
    c = Coach("flexion")
    assert c.update(0.0, angles(5))["form"] == "idle"
    run(c, np.linspace(5, 90, 40))
    assert c.update(2.0, angles(92))["form"] == "good"
    snap = c.update(2.1, angles(93, ("SHRUG",)))
    assert snap["form"] == "fix" and "shrug" in snap["form_issues"][0]


def test_states_progress_in_order():
    c = Coach("flexion")
    seen = []
    for i, v in enumerate(rep_profile(130, 3)):
        s = c.update(i / FPS, angles(v))["state"]
        if not seen or seen[-1] != s:
            seen.append(s)
    assert seen == [REST, RAISING, HOLD, LOWERING, REST]


def test_small_fidget_is_not_a_rep():
    c = Coach("flexion")
    wiggle = np.concatenate([np.linspace(5, 40, 20), np.linspace(40, 5, 20), np.full(30, 5.0)])
    snap, _ = run(c, wiggle)
    assert snap["rep_count"] == 0


def test_missing_measurement_pauses_and_never_reports_zero():
    c = Coach("flexion")
    run(c, np.linspace(5, 80, 30))
    snap = c.update(2.0, {"elevation": {"value": None, "reason": "upper arm not visible"}, "flags": []})
    assert snap["state"] == PAUSED
    assert snap["value"] is None
    assert "unavailable" in snap["cue"]["text"]


def test_compensation_cue_wins_and_is_recorded_on_the_rep():
    c = Coach("flexion")
    prof = rep_profile(125, 5)
    for i, v in enumerate(prof):
        flags = ("TRUNK_LEAN_SAGITTAL",) if 60 <= i < 120 else ()
        snap = c.update(i / FPS, angles(v, flags))
        if 60 <= i < 120:
            assert snap["cue"]["code"] == "TRUNK_LEAN_SAGITTAL"
    assert "TRUNK_LEAN_SAGITTAL" in snap["reps"][0]["flags"]
    assert snap["reps"][0]["correct"] is False
    assert "leaned forward" in snap["reps"][0]["issues"][0]


def test_irrelevant_flags_are_ignored_for_exercise():
    c = Coach("flexion")
    snap = c.update(0.0, angles(5, flags=("ELBOW_DRIFT",)))
    assert snap["cue"] is None or snap["cue"]["code"] != "ELBOW_DRIFT"


def test_target_override_changes_reached():
    c = Coach("flexion")
    c.set_target(150)
    snap, _ = run(c, rep_profile(130, 5))
    assert snap["reps"][0]["reached_target"] is False


def test_voice_cue_not_repeated_within_6s():
    c = Coach("flexion")
    a = c.update(0.0, angles(60, ("SHRUG",)))
    b = c.update(1.0, angles(62, ("SHRUG",)))
    assert a["cue"]["speak"] is True and b["cue"]["speak"] is False


def test_wrong_movement_rep_is_rejected_not_counted():
    c = Coach("flexion")
    for i, v in enumerate(rep_profile(120, 3)):
        snap = c.update(i / FPS, angles(v, movement="abduction" if v > 25 else "rest"))
    assert snap["rep_count"] == 0
    assert any(e["code"] == "REP_REJECTED" for e in snap["events"])


def test_external_rotation_uses_rotation_metric():
    c = Coach("external_rotation")
    vals = np.concatenate([np.linspace(0, 50, 45), np.full(170, 50), np.linspace(50, 0, 45), np.zeros(20)])
    for i, v in enumerate(vals):
        snap = c.update(i / FPS, angles(5, rotation=float(v)))
    assert snap["rep_count"] == 1 and snap["reps"][0]["peak"] == pytest.approx(50, abs=0.5)
