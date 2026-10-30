"""Overlay visibility: no blink around 0.4, no point outside the frame, no invented 0."""

from physiobuddy_hub.core.display_gate import CLOSE_HINT, LandmarkGate, close_hint


def _scores(i, value):
    row = [0.0] * 17
    row[i] = value
    return row


def _point(i, u=0.4, v=0.5):
    row = [None] * 17
    row[i] = [u, v]
    return row


def test_a_joint_under_0_6_is_not_drawn():
    gate = LandmarkGate()
    shown = False
    toggles = 0
    prev = False
    for i in range(40):
        score = 0.45 if i % 2 == 0 else 0.32
        mark = gate.update(_point(8), _scores(8, score), i * 50)[8]
        on = mark is not None
        if on != prev:
            toggles += 1
        prev = on
        shown = shown or on
    assert shown is False
    assert toggles == 0


def test_once_shown_a_dip_above_0_35_does_not_hide():
    gate = LandmarkGate()
    assert gate.update(_point(8), _scores(8, 0.8), 0)[8][2] == 1.0
    toggles = 0
    prev = True
    for i in range(1, 20):
        score = 0.5 if i % 2 else 0.42
        on = gate.update(_point(8), _scores(8, score), i * 50)[8] is not None
        if on != prev:
            toggles += 1
        prev = on
    assert toggles == 0 and prev is True


def test_hold_fades_and_then_drops():
    gate = LandmarkGate()
    gate.update(_point(8), _scores(8, 0.9), 0)
    held = gate.update(_point(8, v=1.4), _scores(8, 0.1), 80)
    assert held[8] is not None and held[8][1] == 0.5 and held[8][2] < 1
    gone = gate.update([None] * 17, _scores(8, 0.0), 200)
    assert gone[8] is None


def test_a_point_below_the_frame_is_not_drawn():
    gate = LandmarkGate()
    assert gate.update(_point(6, u=0.5, v=1.4), _scores(6, 0.99), 0)[6] is None


def test_a_joint_just_past_the_border_stays_on_the_edge():
    gate = LandmarkGate()
    mark = gate.update(_point(8, u=0.4, v=1.05), _scores(8, 0.9), 0)[8]
    assert mark is not None and mark[1] == 1.0


def test_close_hint_when_hips_are_out_of_frame():
    kp = [None] * 17
    scores = [0.0] * 17
    kp[5], kp[6] = [0.2, 0.7], [0.75, 0.72]
    scores[5] = scores[6] = 0.99
    kp[11], kp[12] = [0.3, 1.3], [0.6, 1.4]
    scores[11] = scores[12] = 0.04
    assert close_hint(kp, scores) == CLOSE_HINT
    kp[11], kp[12] = [0.35, 0.9], [0.62, 0.92]
    scores[11] = scores[12] = 0.9
    kp[5], kp[6] = [0.42, 0.4], [0.58, 0.4]
    assert close_hint(kp, scores) is None
