"""Feature extraction.

``lee24`` reproduces Lee 2024 exactly: for each of 6 channels (acc x/y/z, gyro x/y/z) the minimum,
maximum, mean and variance over the exercise segment = 24 features. Order: channel-major
[acc_x_min, acc_x_max, acc_x_mean, acc_x_var, acc_y_min, ...].
"""

from __future__ import annotations

import numpy as np

CHANNELS = ["acc_x", "acc_y", "acc_z", "gyro_x", "gyro_y", "gyro_z"]
STATS = ["min", "max", "mean", "var"]
LEE24_NAMES = [f"{c}_{s}" for c in CHANNELS for s in STATS]


def lee24(acc: np.ndarray, gyro: np.ndarray) -> np.ndarray:
    """acc, gyro: (T, 3) arrays for one segment -> (24,) feature vector."""
    acc = np.asarray(acc, dtype=float)
    gyro = np.asarray(gyro, dtype=float)
    if acc.ndim != 2 or acc.shape[1] != 3 or gyro.shape != acc.shape:
        raise ValueError(f"expected matching (T,3) arrays, got {acc.shape} and {gyro.shape}")
    if len(acc) < 2:
        raise ValueError("segment too short")
    x = np.concatenate([acc, gyro], axis=1)  # (T, 6)
    stats = np.stack([x.min(0), x.max(0), x.mean(0), x.var(0)], axis=1)  # (6, 4)
    return stats.reshape(-1)


def lee24_matrix(segments) -> np.ndarray:
    return np.stack([lee24(s.acc, s.gyro) for s in segments])
