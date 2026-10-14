"""Load guided recordings written by the hub's ``DatasetRecorder`` (``ml/data/real/<subject>/<session>/*.npz``)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from physiobuddy_hub.recorder import ATTEMPT_INDEX

from .datasets.common import SkeletonSequence
from .synth_skeleton import COMP_FLAGS

log = logging.getLogger(__name__)

# recorder compensation names -> PB-MotionNet comp head index
_COMP = {"SHRUG": "SHRUG", "TRUNK_LEAN": "TRUNK_LEAN", "ELBOW_DRIFT": "ELBOW_DRIFT", "TOO_FAST": "TOO_FAST"}
# In rep blocks only frames at rest or inside an attempt the coach counted carry the block's label.
KEEP_ATTEMPTS = (ATTEMPT_INDEX["rest"], ATTEMPT_INDEX["counted"])


def _runs(mask: np.ndarray) -> list:
    """Contiguous True runs -> [(start, stop)]."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def load_sessions(root: Path, min_frames: int = 30) -> list:
    seqs = []
    for f in sorted(Path(root).glob("*/*/*.npz")):
        z = np.load(f, allow_pickle=False)
        exercise = str(z["exercise"])
        rep_block = exercise != "unknown"
        if rep_block and "attempt" not in z.files:
            log.warning("skipping %s: recorded before per-attempt labels (rejected reps would be mislabelled)", f)
            continue
        keep = np.isin(z["attempt"], KEEP_ATTEMPTS) if rep_block else np.ones(len(z["points"]), bool)
        correct = int(z["correct"])
        comp = np.full(len(COMP_FLAGS), -1, np.int64)
        if rep_block:
            comp[:4] = 0                     # scripted blocks: only the scripted mistake is present
            c = str(z["comp"])
            if c in _COMP:
                comp[COMP_FLAGS.index(_COMP[c])] = 1
        base = float(z["shrug_baseline"])
        for k, (a, b) in enumerate(_runs(keep)):
            if b - a < min_frames:
                continue
            seqs.append(SkeletonSequence(
                subject=str(z["subject"]), exercise=exercise, side=str(z["side"]),
                points=z["points"][a:b].astype(float), fps=30.0, source="real",
                name=f"{f.parent.name}/{f.stem}#{k}", correct=None if correct < 0 else bool(correct),
                up_cam=z["up_cam"].astype(float),
                meta={"phase": z["phase"][a:b].astype(np.int64), "comp": comp, "restricted": bool(z["restricted"]),
                      "shrug_baseline": None if np.isnan(base) else base}))
    return seqs
