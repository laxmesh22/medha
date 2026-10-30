"""Display smoothing never invents a joint, and light follows a step sooner than normal."""

from physiobuddy_hub.core.pose_smooth import DisplayPose


def _arm(x):
    return [[x, 0.0, 0.0]] + [None] * 16


def test_off_returns_the_measured_pose():
    pose = DisplayPose("off")
    kp, uv = _arm(0.2), [[0.4, 0.6]]
    out_kp, out_uv = pose.apply(kp, uv, 0.0)
    assert out_kp is kp and out_uv is uv


def test_a_missing_joint_stays_missing():
    pose = DisplayPose("light")
    out, uv = pose.apply(_arm(1.0), [None], 0.0)
    assert out[1] is None and uv == [None]
    out, _ = pose.apply([None] * 17, None, 50.0)
    assert out[0] is None
    out, _ = pose.apply(_arm(4.0), None, 100.0)
    assert out[0][0] == 4.0


def test_light_follows_a_step_sooner_than_normal():
    light, normal = DisplayPose("light"), DisplayPose("normal")
    t = 0.0
    for _ in range(12):
        light.apply(_arm(0.0), None, t)
        normal.apply(_arm(0.0), None, t)
        t += 50.0
    t += 50.0
    got_l, _ = light.apply(_arm(1.0), None, t)
    got_n, _ = normal.apply(_arm(1.0), None, t)
    assert got_l[0][0] > got_n[0][0]
    assert 0.0 < got_l[0][0] < 1.3
