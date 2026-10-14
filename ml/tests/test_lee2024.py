import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pbml.data import G, Segment, load_dataset, save_segment, simulate_segment, synthetic_dataset  # noqa: E402
from pbml.exercises import CLASS_IDS  # noqa: E402
from pbml.features import LEE24_NAMES, lee24  # noqa: E402
from pbml.lee2024 import HIDDEN, evaluate_loso, evaluate_random_split, make_model  # noqa: E402


def test_lee24_feature_layout():
    acc = np.array([[1.0, 2, 3], [3, 4, 5]])
    gyro = np.array([[10.0, 0, -10], [20, 0, -30]])
    f = lee24(acc, gyro)
    assert f.shape == (24,) and len(LEE24_NAMES) == 24
    # acc_x: min 1, max 3, mean 2, var 1
    np.testing.assert_allclose(f[:4], [1, 3, 2, 1])
    # gyro_z: min -30, max -10, mean -20, var 100
    np.testing.assert_allclose(f[20:24], [-30, -10, -20, 100])


def test_lee24_rejects_bad_shapes():
    with pytest.raises(ValueError):
        lee24(np.zeros((10, 3)), np.zeros((9, 3)))


def test_model_matches_paper_architecture():
    mlp = make_model().steps[-1][1]
    assert mlp.hidden_layer_sizes == HIDDEN == (8, 16, 32, 64, 128)
    assert mlp.activation == "relu"


def test_virtual_imu_at_rest_measures_gravity():
    params = {"upper_arm": 0.3, "forearm": 0.25, "speed": 1.0, "amp": 0.0, "mount": np.eye(3),
              "gyro_bias": np.zeros(3)}
    seg = simulate_segment("abduction_band", params, np.random.default_rng(0), seconds=2)
    # amp=0 -> arm hangs still: |specific force| ~ g, gyro ~ 0 (plus noise)
    assert np.linalg.norm(seg.acc.mean(0)) == pytest.approx(G, abs=0.1)
    assert np.abs(seg.gyro.mean(0)).max() < 1.0


def test_csv_round_trip(tmp_path):
    seg = Segment("S01", "er_band", np.random.rand(50, 3), np.random.rand(50, 3), name="rep_00")
    save_segment(tmp_path, seg)
    (back,) = load_dataset(tmp_path)
    assert (back.subject, back.exercise, back.name) == ("S01", "er_band", "rep_00")
    np.testing.assert_allclose(back.acc, seg.acc, atol=1e-4)


def test_protocols_run_and_loso_never_leaks():
    segs = synthetic_dataset(n_subjects=4, reps_per_exercise=3, exercises=CLASS_IDS[:4])
    r = evaluate_random_split(segs)
    l = evaluate_loso(segs)  # asserts no subject overlap internally
    assert 0 <= r.accuracy <= 1 and 0 <= l.accuracy <= 1
    assert len(l.per_fold) == 4
    assert l.confusion.sum() == len(segs)
