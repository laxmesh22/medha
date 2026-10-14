import itertools
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from physiobuddy_hub.api.server import create_app
from physiobuddy_hub.recorder import PREP_S, PROTOCOLS, DatasetRecorder
from test_pipeline import pipeline  # noqa: F401  (fixture)

FPS = 30.0
KP = [[0.0, 0.0, 2.0]] * 17


def ang(shrug=0.5):
    return {"shrug_index": {"value": shrug, "quality": "good", "reason": None}, "flags": []}


def feed(rec, seconds, t0, rep_count=0, state="rest"):
    changed, t = False, t0
    for _ in range(int(seconds * FPS)):
        changed |= rec.on_frame(t, 0, KP, ang(), {"state": state, "rep_count": rep_count}, (0, -1, 0))
        t += 1000 / FPS
    return changed, t


def test_consent_and_subject_id_are_enforced(tmp_path):
    rec = DatasetRecorder(tmp_path)
    with pytest.raises(ValueError, match="consent"):
        rec.start("S01", "right", consent=False)
    with pytest.raises(ValueError, match="subject_id"):
        rec.start("../evil", "right", consent=True)
    assert not rec.active and not any(tmp_path.iterdir())


def test_protocol_shape():
    blocks = PROTOCOLS["full"]()
    kinds = [b.kind for b in blocks]
    assert kinds[0] == "rest" and kinds[-1] == "timed" and blocks[-1].duration_s == 120
    assert sum(b.restricted for b in blocks) == 3
    assert {b.comp for b in blocks if b.comp} == {"SHRUG", "TRUNK_LEAN", "ELBOW_DRIFT", "TOO_FAST"}
    assert all(b.reps == 8 for b in blocks if b.id.endswith("_correct"))


def test_rest_block_sets_baseline_and_slices(tmp_path):
    rec = DatasetRecorder(tmp_path)
    rec.start("S01", "left", consent=True, protocol="quick", session_id="sess")
    changed, t = feed(rec, PREP_S + 5.0 + 0.1, 0.0)
    assert changed and rec.idx == 1 and rec.baseline_ready
    assert rec.shrug_baseline == pytest.approx(0.5)
    z = np.load(tmp_path / "S01" / "sess" / "00_rest.npz")
    assert z["points"].shape[1:] == (17, 3) and str(z["side"]) == "left"
    assert len(z["points"]) == pytest.approx(5.0 * FPS, abs=3)       # prep frames excluded
    assert "Block 2" in rec.announce


def test_rep_block_finishes_on_coach_reps_and_labels_phase(tmp_path):
    rec = DatasetRecorder(tmp_path)
    rec.start("S02", "right", consent=True, protocol="quick", session_id="s")
    _, t = feed(rec, PREP_S + 5.1, 0.0)                               # rest block done
    b = rec.block
    assert b.id == "flexion_correct" and b.reps == 4
    _, t = feed(rec, PREP_S + 1, t, rep_count=0, state="raising")
    assert rec.idx == 1
    changed, t = feed(rec, 0.1, t, rep_count=4, state="rest")
    assert changed and rec.block.id == "abduction_correct"
    z = np.load(tmp_path / "S02" / "s" / "01_flexion_correct.npz")
    assert int(z["correct"]) == 1 and bool(z["complete"]) and str(z["exercise"]) == "flexion"
    assert set(z["phase"].tolist()) <= {0, 1}


def test_rejected_attempts_are_labelled_per_frame(tmp_path):
    rec = DatasetRecorder(tmp_path)
    rec.start("S06", "right", consent=True, protocol="quick", session_id="s")
    _, t = feed(rec, PREP_S + 5.1, 0.0)                               # rest block done
    _, t = feed(rec, PREP_S + 1, t)                                   # prep + 1 s rest
    _, t = feed(rec, 2, t, rep_count=0, state="raising")              # attempt 1 ...
    _, t = feed(rec, 1, t, rep_count=0, state="rest")                 # ... rejected (no rep counted)
    _, t = feed(rec, 2, t, rep_count=0, state="hold")                 # attempt 2 ...
    _, t = feed(rec, 1, t, rep_count=1, state="rest")                 # ... counted
    _, t = feed(rec, 1, t, rep_count=1, state="raising")              # attempt 3 cut off by stop
    rec.stop()
    z = np.load(tmp_path / "S06" / "s" / "01_flexion_correct.npz")
    a = z["attempt"].tolist()
    runs = [(v, sum(1 for _ in g)) for v, g in itertools.groupby(a)]
    assert [v for v, _ in runs] == [0, 2, 0, 1, 0, 3]                 # rest, rejected, rest, counted, rest, open
    assert [n for _, n in runs][1:] == [60, 30, 60, 30, 30]


def test_next_prev_stop_and_jsonl(tmp_path):
    rec = DatasetRecorder(tmp_path)
    rec.start("S03", "right", consent=True, protocol="quick", session_id="s")
    rec.next()
    rec.next()
    assert rec.idx == 2
    rec.prev()
    assert rec.idx == 1 and rec.block.id == "flexion_correct"
    feed(rec, 1.0, 0.0)
    st = rec.stop()
    assert st["active"] is False
    lines = (tmp_path / "S03" / "s" / "frames.jsonl").read_text().splitlines()
    assert len(lines) == 30 and json.loads(lines[0])["block_id"] == "flexion_correct"
    meta = json.loads((tmp_path / "S03" / "s" / "session.json").read_text())
    assert meta["consent"] is True and meta["protocol"] == "quick"


def test_unknown_block_prompts_every_20s(tmp_path):
    rec = DatasetRecorder(tmp_path)
    rec.start("S04", "right", consent=True, protocol="quick")
    rec.idx = len(rec.blocks) - 1
    rec._begin_block()
    ids = set()
    t = 0.0
    for _ in range(int((PREP_S + 45) * FPS)):
        rec.on_frame(t, 0, KP, ang(), {"state": "rest", "rep_count": 0}, (0, -1, 0))
        ids.add(rec.status()["prompt"])
        t += 1000 / FPS
    assert {"Scratch your head.", "Wave at the camera.", "Adjust your shirt or strap."} <= ids


def test_pipeline_api_recording_flow(pipeline, tmp_path):  # noqa: F811
    pipeline.recorder = DatasetRecorder(tmp_path)
    client = TestClient(create_app(pipeline, {}))
    r = client.post("/api/record/start", json={"subject_id": "S05", "side": "right", "consent": False})
    assert r.status_code == 400
    r = client.post("/api/record/start", json={"subject_id": "S05", "consent": True, "protocol": "quick"})
    assert r.json()["ok"] and r.json()["block"]["id"] == "rest"
    client.post("/api/record/next")
    assert pipeline.coach.ex.id == "flexion"
    pipeline._process(pipeline.source.latest())
    _, state = pipeline.latest_state()
    assert state["recorder"]["block"]["id"] == "flexion_correct"
    assert client.get("/api/record/status").json()["active"] is True
    assert client.post("/api/record/bogus").status_code == 404
    assert client.post("/api/record/stop").json()["active"] is False
