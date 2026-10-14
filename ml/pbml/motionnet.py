"""PB-MotionNet: small causal multimodal TCN that *judges* movement (it never outputs degrees).

Input  x: (B, T, D_IN) per-frame features from ``physiobuddy_hub.ml.features`` (skeleton 36 | IMU 18 | mask 2).
Outputs:
  exercise (B, 6)    flexion, abduction, external_rotation, internal_rotation, pendulum, unknown
  phase    (B, T, 4) rest, raising, hold, lowering (per frame, causal)
  form     (B, 1)    logit of "needs fixing"
  comp     (B, 5)    logits SHRUG, TRUNK_LEAN, ELBOW_DRIFT, TOO_FAST, SHORT_ROM

Skeleton encoder 64 ch and IMU encoder 48 ch: 4 causal residual blocks each, kernel 5, dilations 1-2-4-8
(receptive field 61 frames, about 2 s at 30 Hz). Fusion is gated by the modality mask, and training uses
modality dropout so the same model runs camera-only (today), IMU-only or fused.
"""

from __future__ import annotations

import torch
from torch import nn
import torch.nn.functional as F

from physiobuddy_hub.ml.features import CLASSES, COMP_FLAGS, D_IMU, D_SKEL, PHASES


class CausalBlock(nn.Module):
    def __init__(self, ch: int, k: int, d: int, p_drop: float):
        super().__init__()
        self.pad = (k - 1) * d
        self.conv = nn.Conv1d(ch, ch, k, dilation=d)
        self.mix = nn.Conv1d(ch, ch, 1)
        self.drop = nn.Dropout(p_drop)

    def forward(self, h):
        y = self.conv(F.pad(h, (self.pad, 0)))
        y = self.mix(self.drop(F.gelu(y)))
        return F.gelu(h + y)


class Encoder(nn.Module):
    def __init__(self, d_in: int, ch: int, k: int = 5, dilations=(1, 2, 4, 8), p_drop: float = 0.1):
        super().__init__()
        self.inp = nn.Conv1d(d_in, ch, 1)
        self.blocks = nn.Sequential(*[CausalBlock(ch, k, d, p_drop) for d in dilations])

    def forward(self, x):                       # x: (B, D, T)
        return self.blocks(self.inp(x))


class MotionNet(nn.Module):
    def __init__(self, ch_skel: int = 64, ch_imu: int = 48, ch_fused: int = 64, p_drop: float = 0.1):
        super().__init__()
        self.skel = Encoder(D_SKEL, ch_skel, p_drop=p_drop)
        self.imu = Encoder(D_IMU, ch_imu, p_drop=p_drop)
        self.fuse = nn.Conv1d(ch_skel + ch_imu + 2, ch_fused, 1)
        self.phase = nn.Conv1d(ch_fused, len(PHASES), 1)
        self.pool_proj = nn.Linear(2 * ch_fused, ch_fused)
        self.exercise = nn.Linear(ch_fused, len(CLASSES))
        self.form = nn.Linear(ch_fused, 1)
        self.comp = nn.Linear(ch_fused, len(COMP_FLAGS))

    def forward(self, x):                       # x: (B, T, D_IN)
        x = x.transpose(1, 2)                   # (B, D_IN, T)
        xs, xi, m = x[:, :D_SKEL], x[:, D_SKEL:D_SKEL + D_IMU], x[:, D_SKEL + D_IMU:]
        hs = self.skel(xs) * m[:, :1]
        hi = self.imu(xi) * m[:, 1:2]
        h = F.gelu(self.fuse(torch.cat([hs, hi, m], dim=1)))      # (B, C, T)
        phase = self.phase(h).transpose(1, 2)                      # (B, T, 4)
        g = torch.cat([h[:, :, -1], h.mean(dim=2)], dim=1)         # last step + window context
        g = F.gelu(self.pool_proj(g))
        return self.exercise(g), phase, self.form(g), self.comp(g)


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def modality_dropout(x: torch.Tensor, p: float = 0.3) -> torch.Tensor:
    """Randomly hide one modality (only where both are present) so the model works with either alone."""
    x = x.clone()
    ms, mi = x[:, 0, -2], x[:, 0, -1]
    both = (ms > 0) & (mi > 0)
    drop = (torch.rand(len(x), device=x.device) < p) & both
    which = torch.rand(len(x), device=x.device) < 0.5
    hide_s, hide_i = drop & which, drop & ~which
    x[hide_s, :, :D_SKEL] = 0
    x[hide_s, :, -2] = 0
    x[hide_i, :, D_SKEL:D_SKEL + D_IMU] = 0
    x[hide_i, :, -1] = 0
    return x


def energy(logits: torch.Tensor, temperature: float = 1.0) -> torch.Tensor:
    """Free energy over the *known* classes (excl. unknown); higher = less familiar (Liu et al. 2020)."""
    known = logits[:, :-1]
    return -temperature * torch.logsumexp(known / temperature, dim=1)


def multitask_loss(out, batch, w=(1.0, 0.5, 0.5, 0.5)):
    ex_logits, ph_logits, form_logit, comp_logits = out
    loss = w[0] * F.cross_entropy(ex_logits, batch["exercise"])
    ph = batch["phase"]
    if (ph >= 0).any():
        loss = loss + w[1] * F.cross_entropy(ph_logits.reshape(-1, ph_logits.shape[-1]), ph.reshape(-1),
                                             ignore_index=-1)
    c = batch["correct"]
    if (c >= 0).any():
        sel = c >= 0
        loss = loss + w[2] * F.binary_cross_entropy_with_logits(form_logit[sel, 0], (1 - c[sel]).float())
    cm = batch["comp"]
    sel = cm >= 0
    if sel.any():
        loss = loss + w[3] * F.binary_cross_entropy_with_logits(comp_logits[sel], cm[sel].float())
    return loss
