import numpy as np

from physiobuddy_hub.core.coach import PAUSED, REST, Coach
from test_coach import FPS, angles, rep_profile


def low(elev):
    a = angles(elev)
    a["elevation"]["quality"] = "low"
    a["elevation"]["reason"] = "upper arm length jumped"
    return a


def test_user_pause_discards_rep_in_progress_and_blocks_counting():
    c = Coach("flexion")
    prof = rep_profile(130, 5.5)
    for i, v in enumerate(prof[:90]):  # mid-hold
        c.update(i / FPS, angles(v))
    c.set_paused(True)
    for i, v in enumerate(prof[90:], start=90):
        snap = c.update(i / FPS, angles(v))
        assert snap["state"] == PAUSED and snap["user_paused"] is True
    assert snap["rep_count"] == 0
    assert snap["form"] == "paused"
    assert snap["cue"]["code"] == "USER_PAUSED"


def test_resume_starts_from_rest_and_counts_again():
    c = Coach("flexion")
    c.set_paused(True)
    c.update(0.0, angles(5))
    c.set_paused(False)
    assert c.state == REST and c.user_paused is False
    for i, v in enumerate(rep_profile(130, 5.5)):
        snap = c.update(1.0 + i / FPS, angles(v))
    assert snap["rep_count"] == 1
    codes = [e["code"] for e in snap["events"]]
    assert "USER_PAUSED" in codes and "USER_RESUMED" in codes


def test_pause_survives_exercise_change_until_resumed():
    c = Coach("flexion")
    c.set_paused(True)
    c.set_exercise("abduction")
    assert c.update(0.0, angles(5))["state"] == PAUSED


def test_low_quality_frames_freeze_state_and_show_cue():
    c = Coach("flexion")
    for i, v in enumerate(np.linspace(5, 80, 30)):
        c.update(i / FPS, angles(v))
    state = c.state
    snap = c.update(1.1, low(150))
    assert snap["state"] == state
    assert snap["value"] == 150  # number still visible, only not used
    assert snap["cue"]["code"] == "LOW_QUALITY" and snap["form"] == "paused"
    assert c._peak < 100  # the unreliable 150 deg never became the rep peak


def test_rep_with_many_low_quality_frames_is_rejected():
    c = Coach("flexion")
    prof = rep_profile(130, 5.5)
    for i, v in enumerate(prof):
        a = low(v) if 60 <= i < 200 and i % 2 == 0 else angles(v)  # ~70 low of ~260 rep frames
        snap = c.update(i / FPS, a)
    assert snap["rep_count"] == 0
    assert any(e["code"] == "REP_LOW_QUALITY" for e in snap["events"])


def test_few_low_quality_frames_still_count_but_not_as_hold():
    c = Coach("flexion")
    prof = rep_profile(130, 5.5)
    for i, v in enumerate(prof):
        a = low(v) if 100 <= i < 115 else angles(v)  # 0.5 s glitch during hold
        snap = c.update(i / FPS, a)
    assert snap["rep_count"] == 1
    assert snap["reps"][0]["hold_s"] < 5.5 - 0.3
