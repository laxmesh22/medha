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


def test_stale_sample_becomes_unavailable():
    feed = PhoneStraps()
    feed.push({"sensor": "trunk", "seq": 1, "valid": True, "quat": [1, 0, 0, 0], "gravity": [0, 0, 9.8]})
    time.sleep(0.25)
    view = feed.frame_view()["trunk"]
    assert view["available"] is False
    assert view["quat"] is None
