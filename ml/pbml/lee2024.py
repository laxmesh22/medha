"""Lee et al. 2024 baseline classifier + evaluation protocols.

Model (as published): 24 features -> MLP hidden (8, 16, 32, 64, 128), ReLU -> softmax.
Not reported in the paper (our choices, stated so they are not mistaken for theirs): standardisation of
features, Adam, max_iter=2000, early stopping off, fixed random_state.

Protocols:
* ``random_split``: stratified random 80:20 split of segments (the paper's protocol). The same person
  appears in train and test.
* ``loso``: leave-one-subject-out. Every person is tested on a model that never saw them. This is the
  honest number for a product that meets new patients.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import LeaveOneGroupOut, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import lee24_matrix

HIDDEN = (8, 16, 32, 64, 128)


def make_model(seed: int = 0):
    return make_pipeline(
        StandardScaler(),
        MLPClassifier(hidden_layer_sizes=HIDDEN, activation="relu", solver="adam",
                      max_iter=2000, random_state=seed),
    )


@dataclass
class Report:
    protocol: str
    accuracy: float
    macro_f1: float
    labels: list
    confusion: np.ndarray
    per_fold: list = field(default_factory=list)

    def top_confusions(self, k: int = 5) -> list:
        cm = self.confusion.astype(float)
        rows = cm.sum(1, keepdims=True)
        rates = np.divide(cm, rows, out=np.zeros_like(cm), where=rows > 0)
        np.fill_diagonal(rates, 0)
        idx = np.dstack(np.unravel_index(np.argsort(-rates, axis=None), rates.shape))[0][:k]
        return [(self.labels[i], self.labels[j], round(float(rates[i, j]), 3)) for i, j in idx if rates[i, j] > 0]

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_fold_accuracy": [round(a, 4) for a in self.per_fold],
            "top_confusions": self.top_confusions(),
            "labels": self.labels,
            "confusion": self.confusion.tolist(),
        }


def _xy(segments):
    X = lee24_matrix(segments)
    y = np.array([s.exercise for s in segments])
    groups = np.array([s.subject for s in segments])
    return X, y, groups


def evaluate_random_split(segments, test_size: float = 0.2, seed: int = 0) -> Report:
    X, y, _ = _xy(segments)
    labels = sorted(set(y))
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=test_size, stratify=y, random_state=seed)
    model = make_model(seed).fit(Xtr, ytr)
    pred = model.predict(Xte)
    return Report("random_80_20", accuracy_score(yte, pred), f1_score(yte, pred, average="macro"),
                  labels, confusion_matrix(yte, pred, labels=labels))


def evaluate_loso(segments, seed: int = 0) -> Report:
    X, y, groups = _xy(segments)
    labels = sorted(set(y))
    y_true, y_pred, per_fold = [], [], []
    for tr, te in LeaveOneGroupOut().split(X, y, groups):
        assert not set(groups[tr]) & set(groups[te])  # a subject never leaks into its own test
        model = make_model(seed).fit(X[tr], y[tr])
        pred = model.predict(X[te])
        per_fold.append(accuracy_score(y[te], pred))
        y_true.extend(y[te]); y_pred.extend(pred)
    return Report("loso", accuracy_score(y_true, y_pred), f1_score(y_true, y_pred, average="macro"),
                  labels, confusion_matrix(y_true, y_pred, labels=labels), per_fold)
