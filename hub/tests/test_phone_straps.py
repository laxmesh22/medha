"""Phone-forwarded strap samples stay raw. Missing data is unavailable."""
import time

from physiobuddy_hub.straps.phone_feed import PhoneStraps


def test_valid_sample_is_available_and_invalid_is_not():
    feed = PhoneStraps()
    feed.push({"sensor": "upper_arm", "seq": 3, "valid": True, "quat": [1, 0, 0, 0], "gyro": [0, 0, 0.1],
               "gravity": [0, 0, 9.8]})
    view = feed.frame_view()["upper_arm"]
    assert view["available"] is True
    assert view["quat"][0] == 1
    assert view["gravity"][2] == 9.8

    feed.push({"sensor": "upper_arm", "seq": 4, "valid": False, "quat": [1, 0, 0, 0]})
    view = feed.frame_view()["upper_arm"]
    assert view["available"] is False
    assert view["quat"] is None
    assert view["gravity"] is None


def test_unknown_sensor_and_bad_quat_are_dropped():
    feed = PhoneStraps()
    feed.push({"sensor": "wrist", "seq": 1, "valid": True, "quat": [1, 0, 0, 0]})
    feed.push({"sensor": "forearm", "seq": 1, "valid": True, "quat": [1, 0]})
    assert "wrist" not in feed.frame_view()
    view = feed.frame_view()["forearm"]
    assert view["available"] is False
    assert view["quat"] is None


def test_sensor_reboot_keeps_the_orientation_continuous():
    """Live: the wrist sensor rebooted 3 times and each reboot froze the figure. A rebooted BNO's yaw is new, but the
    limb has not moved, so the yaw step is taken out and the calibration is kept."""
    import numpy as np

    from physiobuddy_hub.core.strap_kin import axis_angle, matrix_to_quat, quat_to_matrix

    tilt = axis_angle([1.0, 0, 0], np.radians(25))
    feed = PhoneStraps()
    feed.push({"sensor": "forearm", "seq": 1, "valid": True, "quat": matrix_to_quat(tilt).tolist()})
    rebooted = axis_angle([0, 0, 1.0], np.radians(70)) @ tilt          # same pose, new yaw reference
    feed.push({"sensor": "forearm", "seq": 2, "valid": False, "reset": True})
    feed.push({"sensor": "forearm", "seq": 3, "valid": True, "quat": matrix_to_quat(rebooted).tolist()})
    assert feed.generation == 0
    assert np.allclose(quat_to_matrix(feed.frame_view()["forearm"]["quat"]), tilt, atol=1e-3)
    moved = axis_angle([0, 0, 1.0], np.radians(70)) @ axis_angle([1.0, 0, 0], np.radians(60))
    feed.push({"sensor": "forearm", "seq": 4, "valid": True, "quat": matrix_to_quat(moved).tolist()})
    assert np.allclose(quat_to_matrix(feed.frame_view()["forearm"]["quat"]),
                       axis_angle([1.0, 0, 0], np.radians(60)), atol=1e-3)   # later motion stays in the old frame
    row = [d for d in feed.status()["devices"] if d["slot"] == "forearm"][0]
    assert row["resets"] == 1 and row["reanchored"] == 1


def test_sensor_reboot_without_a_previous_sample_drops_the_calibration():
    feed = PhoneStraps()
    feed.push({"sensor": "forearm", "seq": 1, "valid": True, "quat": [1, 0, 0, 0], "reset": True})
    assert feed.generation == 1


def test_stale_sample_becomes_unavailable():
    feed = PhoneStraps()
    feed.push({"sensor": "trunk", "seq": 1, "valid": True, "quat": [1, 0, 0, 0], "gravity": [0, 0, 9.8]})
    time.sleep(0.25)
    view = feed.frame_view()["trunk"]
    assert view["available"] is False
    assert view["quat"] is None
