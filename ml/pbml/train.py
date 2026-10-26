"""Dataset assembly, augmentation, training, grouped (LOSO) evaluation and ONNX export for PB-MotionNet."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut

from . import augment
from . import straps as straps_mod
from .datasets.common import SkeletonSequence
from .features_multimodal import (
    CLASSES, COMP_FLAGS, D_IMU, D_IN, D_SKEL, FEATURE_VERSION, FPS, IMU_SENSORS, PHASES, STRIDE, WINDOW, Sample,
    from_imu_segment, from_skeleton_sequence,
)
from .motionnet import MotionNet, energy, modality_dropout, multitask_loss, n_params

UNKNOWN = CLASSES.index("unknown")
NO_ROM_AUG = {"unknown", "pendulum"}


# ------------------------------------------------------------------------------------------ data
def augmented_copies(seq: SkeletonSequence, rng, k: int, straps: bool = False) -> list:
    """``k`` augmented versions of a skeleton sequence; phase labels follow the time warp. With ``straps`` the
    virtual straps are re-derived from the augmented motion (after ROM restriction and time warp, before the camera
    viewpoint / noise), so camera and straps agree in every copy."""
    out = []
    for _ in range(k):
        pts, up = seq.points, seq.up_cam
        if seq.exercise not in NO_ROM_AUG and rng.random() < 0.5:
            pts = augment.restrict_rom(pts, seq.side, float(rng.uniform(0.45, 0.85)), up)
        factor = float(rng.uniform(0.75, 1.35))
        n = max(2, int(round(len(pts) * factor)))
        src = np.clip(np.round(np.linspace(0, len(pts) - 1, n)).astype(int), 0, len(pts) - 1)
        pts = augment.time_warp(pts, factor)
        segs = straps_mod.segments_from_points(pts, seq.side, up) if straps else None
        pts, up = augment.viewpoint(pts, up, float(rng.uniform(-20, 20)), float(rng.uniform(-8, 8)))
        pts = augment.occlude(augment.jitter(pts, rng), rng)
        meta = dict(seq.meta)
        if "phase" in meta:
            meta["phase"] = np.asarray(meta["phase"])[src]
        s2 = SkeletonSequence(seq.subject, seq.exercise, seq.side, pts, seq.fps, seq.source,
                              seq.name + "~aug", seq.correct, up, meta)
        out.append((s2, segs))
    return out


def _strap_frames(segs, side: str, rng, p_drop: float = 0.1):
    """Freshly worn + calibrated virtual straps; ``p_drop`` of the time one strap is missing."""
    if segs is None:
        return None
    drop = ()
    if rng.random() < p_drop:
        drop = (str(rng.choice(["forearm", "trunk"])),)
    return straps_mod.strap_frames(segs, side, rng, drop=drop)


def samples_from_sequences(items: list, rng, n_aug: int = 2) -> list:
    """items: SkeletonSequence or (SkeletonSequence, segment orientations from ``straps.segments_from_points``).
    Returns Samples incl. augmented copies; paired items get virtual strap features."""
    out = []
    for it in items:
        seq, segs = (it, None) if isinstance(it, SkeletonSequence) else it
        out.append(from_skeleton_sequence(seq, straps=_strap_frames(segs, seq.side, rng, p_drop=0.0)))
        for s2, segs2 in augmented_copies(seq, rng, n_aug, straps=segs is not None):
            out.append(from_skeleton_sequence(s2, straps=_strap_frames(segs2, seq.side, rng)))
    return out


def samples_from_imu_segments(segs: list, rng=None, n_aug: int = 0) -> list:
    """IMU-only Samples; ``n_aug`` copies with strap mounting rotation, bias, scaling, noise and time warp."""
    out = []
    for s in segs:
        out.append(from_imu_segment(s))
        for _ in range(n_aug if rng is not None else 0):
            factor = float(rng.uniform(0.75, 1.35))
            src = np.clip(np.round(np.linspace(0, len(s.acc) - 1, max(2, int(round(len(s.acc) * factor))))),
                          0, len(s.acc) - 1).astype(int)
            acc, gyro = augment.imu_augment(s.acc[src], s.gyro[src] / factor, rng)   # slower = lower rates
            out.append(from_imu_segment(replace(s, acc=acc, gyro=gyro, name=s.name + "~aug")))
    return out


@dataclass
class Windows:
    x: np.ndarray          # (N, W, D)
    exercise: np.ndarray   # (N,)
    phase: np.ndarray      # (N, W)
    correct: np.ndarray    # (N,)
    comp: np.ndarray       # (N, C)
    groups: np.ndarray     # (N,) subject id
    source: np.ndarray     # (N,)
    aug: np.ndarray        # (N,) bool: window comes from an augmented copy (train only, never scored)

    def __len__(self):
        return len(self.x)

    def subset(self, idx) -> "Windows":
        return Windows(*(getattr(self, f)[idx] for f in self.__dataclass_fields__))


def make_windows(samples: list, window: int = WINDOW, stride: int = STRIDE) -> Windows:
    xs, ex, ph, co, cm, gr, so, au = [], [], [], [], [], [], [], []
    for s in samples:
        x, p = s.x, s.phase
        if len(x) < window:
            pad = window - len(x)
            x = np.concatenate([np.repeat(x[:1], pad, 0), x])
            p = np.concatenate([np.full(pad, -1), p])
        for a in range(0, len(x) - window + 1, stride):
            xs.append(x[a:a + window]); ph.append(p[a:a + window])
            ex.append(s.exercise); co.append(s.correct); cm.append(s.comp); gr.append(s.subject); so.append(s.source)
            au.append("~aug" in s.name)
    return Windows(np.asarray(xs, np.float32), np.asarray(ex, np.int64), np.asarray(ph, np.int64),
                   np.asarray(co, np.int64), np.asarray(cm, np.int64), np.asarray(gr), np.asarray(so),
                   np.asarray(au, bool))


# -------------------------------------------------------------------------------------- training
def train_model(w: Windows, epochs: int = 25, lr: float = 2e-3, batch: int = 128, seed: int = 0,
                p_modality: float = 0.3, verbose: bool = False) -> MotionNet:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = MotionNet()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=max(1, epochs * int(np.ceil(len(w) / batch))))
    counts = np.bincount(w.exercise, minlength=len(CLASSES)).astype(float)
    p_class = np.where(counts > 0, 1.0 / np.maximum(counts, 1), 0)[w.exercise]
    p_class /= p_class.sum()                      # class-balanced sampling
    tensors = {k: torch.from_numpy(getattr(w, k)) for k in ("x", "exercise", "phase", "correct", "comp")}
    for ep in range(epochs):
        model.train()
        idx = rng.choice(len(w), size=len(w), p=p_class)
        tot = 0.0
        for a in range(0, len(idx), batch):
            b = torch.from_numpy(idx[a:a + batch])
            bt = {k: v[b] for k, v in tensors.items()}
            bt["x"] = modality_dropout(bt["x"], p_modality)
            loss = multitask_loss(model(bt["x"]), bt)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item() * len(b)
        if verbose:
            print(f"  epoch {ep + 1:>3}/{epochs}  loss {tot / len(idx):.4f}")
    model.eval()
    return model


@torch.no_grad()
def predict(model: MotionNet, x: np.ndarray, batch: int = 512) -> dict:
    model.eval()
    outs = [model(torch.from_numpy(x[a:a + batch])) for a in range(0, len(x), batch)]
    ex = torch.cat([o[0] for o in outs])
    return {"exercise_logits": ex.numpy(), "energy": energy(ex).numpy(),
            "phase": torch.cat([o[1] for o in outs]).argmax(-1).numpy(),
            "form_p": torch.sigmoid(torch.cat([o[2] for o in outs]))[:, 0].numpy(),
            "comp_p": torch.sigmoid(torch.cat([o[3] for o in outs])).numpy()}


def calibrate_energy(model: MotionNet, w: Windows, mode: str = "fused", keep: float = 0.95) -> float:
    """Energy threshold accepting ``keep`` of known-class windows fed in ``mode`` (others become unknown).

    Masking a modality raises the energy, so each input mode (camera-only, IMU-only, fused) gets its own.
    """
    sel = (w.exercise != UNKNOWN) & has_modality(w, mode)
    if not sel.any():
        return float("inf")
    return float(np.quantile(predict(model, mask_modality(w.x[sel], mode))["energy"], keep))


def calibrate_all(model: MotionNet, w: Windows, keep: float = 0.95) -> dict:
    return {m: calibrate_energy(model, w, m, keep) for m in ("skeleton", "imu", "fused")}


def decide(pred: dict, energy_thr: float) -> np.ndarray:
    lab = pred["exercise_logits"].argmax(1)
    lab[pred["energy"] > energy_thr] = UNKNOWN
    return lab


def mask_modality(x: np.ndarray, mode: str) -> np.ndarray:
    x = x.copy()
    if mode == "skeleton":
        x[:, :, D_SKEL:D_SKEL + D_IMU] = 0
        x[:, :, -1] = 0
    elif mode == "imu":
        x[:, :, :D_SKEL] = 0
        x[:, :, -2] = 0
    return x


def has_modality(w: Windows, mode: str) -> np.ndarray:
    s, i = w.x[:, 0, -2] > 0, w.x[:, 0, -1] > 0
    return {"skeleton": s, "imu": i, "fused": s & i}[mode]


def metrics(y_true, y_pred, w: Windows, pred: Optional[dict] = None) -> dict:
    labels = list(range(len(CLASSES)))
    out = {"n": int(len(y_true)), "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
           "macro_f1": round(float(f1_score(y_true, y_pred, labels=sorted(set(y_true)), average="macro")), 4)}
    unk = y_true == UNKNOWN
    if unk.any():
        out["unknown_rejection"] = round(float(np.mean(y_pred[unk] == UNKNOWN)), 4)
    if (~unk).any():
        out["known_false_reject"] = round(float(np.mean(y_pred[~unk] == UNKNOWN)), 4)
    cm = np.zeros((len(CLASSES), len(CLASSES)), int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    out["confusion"] = cm.tolist()
    if pred is not None:
        sel = w.phase >= 0
        if sel.any():
            out["phase_frame_acc"] = round(float(np.mean(pred["phase"][sel] == w.phase[sel])), 4)
        lab = w.correct >= 0
        if lab.any() and len(set(w.correct[lab])) == 2:
            fix_true = w.correct[lab] == 0
            fix_pred = pred["form_p"][lab] > 0.5
            out["form_sensitivity"] = round(float(np.mean(fix_pred[fix_true])), 4)
            out["form_specificity"] = round(float(np.mean(~fix_pred[~fix_true])), 4)
    return out


MIN_FIT_SUBJECTS = 3        # never shrink a source's training people below this to make a calibration set
IN_SAMPLE_KEEP = 0.99       # looser cutoff when calibrating on training people (their energies are optimistic)


def calibration_split(w: Windows, idx: np.ndarray, frac: float = 0.2, seed: int = 0,
                      min_fit: int = MIN_FIT_SUBJECTS) -> tuple:
    """Split ``idx`` by subject into (fit, calibration). Per source, ``frac`` of its subjects (>= 1) are held out
    so every input mode gets a threshold tuned on people the model never trained on, but only when at least
    ``min_fit`` subjects of that source remain for training. With fewer people (small or synthetic runs) holding
    one out would leave the network almost nothing to learn from, so that source is not split."""
    rng = np.random.default_rng(seed)
    groups, sources = w.groups[idx], w.source[idx]
    cal = set()
    for src in sorted(set(sources)):
        g = sorted(set(groups[sources == src]) - cal)
        n_cal = max(1, int(round(frac * len(g))))
        if len(g) - n_cal >= min_fit:
            cal |= set(rng.choice(g, size=n_cal, replace=False).tolist())
    is_cal = np.isin(groups, list(cal))
    return idx[~is_cal], idx[is_cal], sorted(cal)


def fit_and_calibrate(w: Windows, idx: np.ndarray, epochs: int, seed: int) -> tuple:
    """Train on ``idx`` minus calibration subjects; energy thresholds from their original windows only.

    An input mode with no held-out calibration people (too few subjects) falls back to the training people's
    original windows with the looser ``IN_SAMPLE_KEEP`` cutoff; the returned info says which modes did.
    """
    fit, cal, cal_subjects = calibration_split(w, idx, seed=seed)
    model = train_model(w.subset(fit), epochs=epochs, seed=seed)
    cal = cal[~w.aug[cal]]
    thr = calibrate_all(model, w.subset(cal)) if len(cal) else {m: float("inf") for m in ("skeleton", "imu", "fused")}
    in_sample = [m for m, v in thr.items() if not np.isfinite(v)]
    if in_sample:
        fit_orig = fit[~w.aug[fit]]
        fallback = calibrate_all(model, w.subset(fit_orig), keep=IN_SAMPLE_KEEP)
        thr.update({m: fallback[m] for m in in_sample})
    return model, thr, {"held_out": cal_subjects, "in_sample_modes": in_sample}


def grouped_cv(w: Windows, n_folds: Optional[int] = None, epochs: int = 25, seed: int = 0,
               modes=("skeleton", "imu", "fused"), verbose: bool = False) -> dict:
    """LOSO when ``n_folds`` is None, else GroupKFold. One model per fold, evaluated per input modality.

    Test subjects are scored on their original (non-augmented) windows only; the unknown cutoff is tuned on
    calibration subjects held out from the fold's training people.
    """
    groups = w.groups
    splitter = LeaveOneGroupOut() if n_folds is None else GroupKFold(n_splits=min(n_folds, len(set(groups))))
    agg = {m: ([], [], []) for m in modes}
    calibration = []
    for k, (tr, te) in enumerate(splitter.split(w.x, w.exercise, groups)):
        assert not set(groups[tr]) & set(groups[te])
        model, thr, cal_info = fit_and_calibrate(w, tr, epochs=epochs, seed=seed + k)
        calibration.append({"fold": k + 1, **cal_info})
        te = te[~w.aug[te]]
        wt = w.subset(te)
        for m in modes:
            sel = has_modality(wt, m)
            if not sel.any():
                continue
            ws = wt.subset(np.flatnonzero(sel))
            pr = predict(model, mask_modality(ws.x, m))
            agg[m][0].append(ws.exercise); agg[m][1].append(decide(pr, thr[m])); agg[m][2].append((ws, pr))
        if verbose:
            print(f"  fold {k + 1}: test subjects {sorted(set(groups[te].tolist()))}, calibration "
                  f"{cal_info['held_out']}" + (f" (in-sample: {', '.join(cal_info['in_sample_modes'])})"
                                               if cal_info["in_sample_modes"] else ""), flush=True)
    out = {}
    for m, (yt, yp, extra) in agg.items():
        if not yt:
            out[m] = None
            out.setdefault("not_measured", {})[m] = "no source in this run records the inputs this mode needs"
            continue
        wcat = Windows(*(np.concatenate([getattr(e[0], f) for e in extra])
                         for f in Windows.__dataclass_fields__))
        pcat = {k: np.concatenate([e[1][k] for e in extra]) for k in extra[0][1]}
        out[m] = metrics(np.concatenate(yt), np.concatenate(yp), wcat, pcat)
    out["protocol"] = "loso" if n_folds is None else f"group_{n_folds}fold"
    out["scored"] = "original windows of held-out subjects; unknown cutoff tuned on held-out calibration subjects"
    out["calibration"] = calibration
    if any(c["in_sample_modes"] for c in calibration):
        out["scored"] += (f" (where a source had fewer than {MIN_FIT_SUBJECTS + 1} training subjects, tuned "
                          f"in-sample at the {IN_SAMPLE_KEEP:.0%} quantile; see 'calibration')")
    return out


# ---------------------------------------------------------------------------------------- export
def export_onnx(model: MotionNet, out_dir: Path, energy_thr: dict, metrics_: dict, sources: list,
                extra: Optional[dict] = None) -> Path:
    """``energy_thr``: per input mode {"skeleton", "imu", "fused"} (see ``calibrate_all``).

    Every export starts unvalidated: the hub shows its opinion but lets it veto nothing until
    ml/validate_real.py has passed this exact ``model_version`` on held-out Physio Buddy recordings.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "pb_motionnet.onnx"
    model.eval()
    dummy = torch.zeros(1, WINDOW, D_IN)
    torch.onnx.export(model, (dummy,), str(path), input_names=["x"],
                      output_names=["exercise_logits", "phase_logits", "form_logit", "comp_logits"],
                      dynamic_axes={"x": {0: "batch"}}, opset_version=17, dynamo=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    meta = {
        "model_version": f"pb-motionnet-{time.strftime('%Y%m%d')}-{digest}",
        "feature_schema": {"version": FEATURE_VERSION, "fps": FPS, "window": WINDOW, "d_in": D_IN, "d_skel": D_SKEL,
                           "d_imu": D_IMU, "imu_sensors": list(IMU_SENSORS),
                           "classes": list(CLASSES), "phases": list(PHASES), "comp_flags": list(COMP_FLAGS),
                           "definition": "physiobuddy_hub.ml.features"},
        "thresholds": {"energy": energy_thr, "unknown_prob": 0.5, "comp_prob": 0.7, "autodetect_conf": 0.8},
        "params": n_params(model), "training_sources": sources, "loso_metrics": metrics_,
        "exported": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **(extra or {}),
        "real_validation": {"passed": False, "imu_passed": False,
                            "reason": "not yet tested on held-out Physio Buddy recordings (ml/validate_real.py)"},
    }
    (out_dir / "pb_motionnet.json").write_text(json.dumps(meta, indent=1))
    return path
