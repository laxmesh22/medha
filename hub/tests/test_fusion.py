"""Camera + strap fusion for the coach (handoff §9.4): never averaged, strap-only counting is an operator choice."""
from physiobuddy_hub.core.coach import Coach
from physiobuddy_hub.core.fusion import fuse


def ang(elev=None, elbow=None, flags=(), quality="good", movement="flexion"):
    return {"elevation": {"value": elev, "quality": quality}, "elbow_flexion": {"value": elbow, "quality": quality},
            "flags": list(flags), "movement": movement}


def test_camera_is_the_measurement_and_the_bands_check_it():
    out, info = fuse(ang(90), ang(95), "flexion", "elevation", strap_coach=False)
    assert info["source"] == "camera" and out["elevation"]["value"] == 90 and out["elevation"]["quality"] == "good"
    assert info["disagree_deg"] == 5.0


def test_disagreement_is_not_counted_and_never_averaged():
    out, info = fuse(ang(90), ang(130), "flexion", "elevation", strap_coach=False)
    assert out["elevation"]["value"] == 90 and out["elevation"]["quality"] == "low"
    assert "disagree" in out["elevation"]["reason"] and info["disagree_deg"] == 40.0


def test_bands_count_only_when_the_station_allows_it():
    out, info = fuse(ang(None), ang(80), "flexion", "elevation", strap_coach=False)
    assert info["source"] is None and out["elevation"]["value"] is None
    out, info = fuse(ang(None), ang(80), "flexion", "elevation", strap_coach=True)
    assert info["source"] == "straps" and out["elevation"]["value"] == 80


def test_uncalibrated_bands_are_never_used():
    out, info = fuse(ang(None), ang(80, quality="low"), "flexion", "elevation", strap_coach=True)
    assert info["source"] is None and out["elevation"]["value"] is None


def test_bands_add_a_bent_elbow_and_waist_lean():
    out, info = fuse(ang(90), ang(92, elbow=40, flags=["TRUNK_LEAN_SAGITTAL", "SHRUG"]), "flexion", "elevation", False)
    assert info["strap_flags"] == ["ELBOW_BENT", "TRUNK_LEAN_SAGITTAL"] and "SHRUG" not in out["flags"]
    out, _ = fuse(ang(90), ang(92, elbow=40), "external_rotation", "elevation", False)
    assert "ELBOW_BENT" not in out["flags"]                       # rotation is done with the elbow bent


def test_coach_tells_the_patient_to_straighten_the_elbow():
    coach = Coach("flexion")
    for i, v in enumerate((10, 40, 70, 90)):
        judged, _ = fuse(ang(v), ang(v, elbow=45), "flexion", "elevation", False)
        snap = coach.update(i * 0.2, judged)
    assert snap["form"] == "fix" and snap["cue"]["text"] == "Keep your elbow straight."
