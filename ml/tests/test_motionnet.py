import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

torch = pytest.importorskip("torch")
ort = pytest.importorskip("onnxruntime")

from pbml import train as T  # noqa: E402
from pbml.features_multimodal import CLASSES, D_IN, D_SKEL, WINDOW  # noqa: E402
from pbml.motionnet import MotionNet, modality_dropout, n_params  # noqa: E402
from pbml.synth_skeleton import make_sequence, subject_params, synthetic_people  # noqa: E402


@pytest.fixture(scope="module")
def windows():
    rng = np.random.default_rng(0)
    items = synthetic_people(n_subjects=3, seqs_per_class=1, seed=1)
    return T.make_windows(T.samples_from_sequences(items, rng, n_aug=0))


def test_model_size_and_shapes():
    m = MotionNet()
    assert 120_000 < n_params(m) < 220_000
    ex, ph, form, comp = m(torch.zeros(3, WINDOW, D_IN))
    assert ex.shape == (3, len(CLASSES)) and ph.shape == (3, WINDOW, 4) and form.shape == (3, 1) and comp.shape == (3, 5)


def test_model_is_causal():
    """A change at the last frame must not change earlier per-frame phase outputs."""
    m = MotionNet().eval()
    x = torch.randn(1, WINDOW, D_IN)
    x2 = x.clone()
    x2[0, -1] += 5.0
    with torch.no_grad():
        a, b = m(x)[1], m(x2)[1]
    assert torch.allclose(a[0, :-1], b[0, :-1], atol=1e-5)


def test_modality_dropout_only_hides_one_present_modality():
    x = torch.ones(200, WINDOW, D_IN)
    y = modality_dropout(x, p=1.0)
    s, i = y[:, 0, -2], y[:, 0, -1]
    assert torch.all((s + i) == 1)
    assert torch.all(y[s == 0, :, :D_SKEL] == 0)


def test_synthetic_paired_sequence_has_both_modalities():
    rng = np.random.default_rng(0)
    seq, acc, gyro = make_sequence("abduction", "left", rng, subject_params(rng), comp="SHRUG")
    s = T.samples_from_sequences([(seq, acc, gyro)], rng, n_aug=1)
    assert len(s) == 2 and all(x.x[:, -2].mean() > 0.9 and x.x[:, -1].mean() > 0.9 for x in s)
    assert s[0].correct == 0 and s[0].comp[0] == 1 and (s[0].phase >= 0).all()


def test_train_export_and_onnx_parity(windows, tmp_path):
    model = T.train_model(windows, epochs=1, batch=256)
    thr = T.calibrate_all(model, windows)
    path = T.export_onnx(model, tmp_path, thr, {"note": "test"}, ["synthetic"])
    meta = json.loads((tmp_path / "pb_motionnet.json").read_text())
    assert meta["feature_schema"]["d_in"] == D_IN and set(meta["thresholds"]["energy"]) == {"skeleton", "imu", "fused"}
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    x = windows.x[:4]
    onnx_out = sess.run(None, {"x": x})
    with torch.no_grad():
        torch_out = model(torch.from_numpy(x))
    for a, b in zip(onnx_out, torch_out):
        np.testing.assert_allclose(a, b.numpy(), atol=1e-4)


def test_grouped_cv_never_leaks_subjects(windows):
    res = T.grouped_cv(windows, n_folds=3, epochs=1, modes=("skeleton",))
    assert res["protocol"] == "group_3fold" and res["skeleton"]["n"] == int(T.has_modality(windows, "skeleton").sum())


@pytest.fixture(scope="module")
def windows_aug():
    rng = np.random.default_rng(0)
    items = synthetic_people(n_subjects=4, seqs_per_class=1, seed=2)
    return T.make_windows(T.samples_from_sequences(items, rng, n_aug=1))


def test_cv_scores_only_original_windows(windows_aug):
    w = windows_aug
    assert w.aug.any() and (~w.aug).any()
    res = T.grouped_cv(w, n_folds=2, epochs=1, modes=("skeleton",))
    assert res["skeleton"]["n"] == int((T.has_modality(w, "skeleton") & ~w.aug).sum())


def test_calibration_subjects_are_held_out(windows_aug):
    w = windows_aug
    fit, cal, subjects = T.calibration_split(w, np.arange(len(w)), frac=0.25)
    assert subjects and not set(w.groups[fit]) & set(w.groups[cal])
    assert set(w.groups[cal]) == set(subjects)


def test_calibration_never_leaves_too_few_training_subjects(windows_aug):
    """With 3 people (as in a small fold), holding one out would leave 2: the source must not be split,
    and the cutoff falls back to in-sample instead of training the network on almost no one."""
    w = windows_aug
    three = np.flatnonzero(np.isin(w.groups, sorted(set(w.groups))[:3]))
    fit, cal, subjects = T.calibration_split(w, three, frac=0.25)
    assert subjects == [] and len(cal) == 0 and len(fit) == len(three)
    model, thr, info = T.fit_and_calibrate(w, three, epochs=1, seed=0)
    assert info["held_out"] == [] and "skeleton" in info["in_sample_modes"]
    assert np.isfinite(thr["skeleton"])


def test_imu_segments_are_augmented():
    from pbml.data import Segment

    rng = np.random.default_rng(0)
    seg = Segment("S1", "flexion", np.tile([0, 0, 9.81], (300, 1)), np.zeros((300, 3)), name="s1")
    s = T.samples_from_imu_segments([seg], rng, n_aug=2)
    assert [x.name for x in s] == ["s1", "s1~aug", "s1~aug"]
    assert not np.allclose(s[0].x[:50], s[1].x[:50])


def test_export_is_advisory_until_validated(windows, tmp_path):
    from physiobuddy_hub.ml.motionnet_infer import MotionNetRunner

    model = T.train_model(windows, epochs=1, batch=256)
    T.export_onnx(model, tmp_path, T.calibrate_all(model, windows), {}, ["synthetic"])
    meta = json.loads((tmp_path / "pb_motionnet.json").read_text())
    assert meta["real_validation"]["passed"] is False
    r = MotionNetRunner.from_dir(tmp_path)
    assert r.available and not r.validated
    meta["real_validation"] = {"passed": True, "model_version": meta["model_version"]}
    (tmp_path / "pb_motionnet.json").write_text(json.dumps(meta))
    assert MotionNetRunner.from_dir(tmp_path).validated


def _record_block(rec, seq, rejected_first: bool):
    """Feed a synthetic rep sequence through the recorder as the coach would report it."""
    from physiobuddy_hub.recorder import PREP_S

    names = ("rest", "raising", "hold", "lowering")
    t, reps, attempts, prev = 0.0, 0, 0, "rest"
    for _ in range(int(PREP_S * 30) + 2):
        rec.on_frame(t, 0, seq.points[0].tolist(), None, {"state": "rest", "rep_count": 0}, (0, -1, 0))
        t += 1000 / 30
    for p, ph in zip(seq.points, seq.meta["phase"]):
        state = names[int(ph)]
        if state == "rest" and prev != "rest":            # attempt ended: coach counts it, except the first
            attempts += 1
            reps += 0 if rejected_first and attempts == 1 else 1
        rec.on_frame(t, 0, p.tolist(), None, {"state": state, "rep_count": reps}, (0, -1, 0))
        prev, t = state, t + 1000 / 30


def test_real_loader_drops_rejected_attempts_and_validator_gates(windows, tmp_path):
    import subprocess

    from physiobuddy_hub.recorder import DatasetRecorder
    from pbml.real import load_sessions

    rng = np.random.default_rng(3)
    seq, _, _ = make_sequence("flexion", "right", rng, subject_params(rng), n_reps=3)
    rec = DatasetRecorder(tmp_path / "real")
    rec.start("V01", "right", consent=True, protocol="quick", session_id="s")
    rec.next()                                            # skip rest calibration
    _record_block(rec, seq, rejected_first=True)
    rec.stop()
    z = np.load(tmp_path / "real" / "V01" / "s" / "01_flexion_correct.npz")
    assert 2 in z["attempt"] and 1 in z["attempt"]          # one rejected, later ones counted
    seqs = load_sessions(tmp_path / "real")
    kept = sum(len(s.points) for s in seqs)
    assert seqs and kept <= int(np.isin(z["attempt"], (0, 1)).sum()) and kept < len(z["points"])

    model = T.train_model(windows, epochs=1, batch=256)
    T.export_onnx(model, tmp_path / "m", T.calibrate_all(model, windows), {}, ["synthetic"])
    out = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "validate_real.py"),
                          "--real", str(tmp_path / "real"), "--model", str(tmp_path / "m"),
                          "--report-dir", str(tmp_path)],
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr
    meta = json.loads((tmp_path / "m" / "pb_motionnet.json").read_text())
    rv = meta["real_validation"]
    assert rv["passed"] is False and rv["model_version"] == meta["model_version"]   # 1 volunteer < 3
    assert rv["n_subjects"] == 1 and rv["imu_passed"] is False
