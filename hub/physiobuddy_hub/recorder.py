"""Guided volunteer recording: scripted, auto-labelled blocks for PB-MotionNet training.

Each block tells the volunteer what to do (spoken by the UI), switches the coach to that exercise and labels
every frame with: scripted exercise, correct / needs_fixing, scripted compensation, restricted-ROM flag and the
coach's phase (rest / raising / hold / lowering). Rep blocks finish when the coach has counted N reps, timed
blocks finish on the clock.

Output (keypoints and angles only, never video), one folder per session:
    <root>/<subject_id>/<session_id>/session.json
    <root>/<subject_id>/<session_id>/frames.jsonl             every frame
    <root>/<subject_id>/<session_id>/<NN>_<block_id>.npz       one slice per finished block (training input)
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from . import __version__

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "ml" / "data" / "real"
PREP_S = 4.0                 # "get ready" lead-in at the start of every block, not used for training
UNKNOWN_PROMPT_S = 20.0
SUBJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
PHASE_INDEX = {"rest": 0, "raising": 1, "hold": 2, "lowering": 3}
# Per-frame outcome of the coach attempt the frame belongs to. Only "rest" and "counted" frames of a rep
# block carry the block's label; rejected / unfinished attempts are not what the block says they are.
ATTEMPT_INDEX = {"rest": 0, "counted": 1, "rejected": 2, "incomplete": 3, "paused": 4}
_ACTIVE = ("raising", "hold", "lowering")

UNKNOWN_PROMPTS = (
    "Scratch your head.", "Wave at the camera.", "Adjust your shirt or strap.", "Reach for a phone in your pocket.",
    "Take a sip of water, or pretend to.", "Step out of the frame and come back.",
)


@dataclass
class Block:
    id: str
    kind: str                       # rest | reps | timed
    exercise: str                   # coach exercise id, or "unknown"
    title: str
    prompt: str
    reps: int = 0
    duration_s: float = 0.0
    correct: Optional[bool] = True
    comp: Optional[str] = None      # scripted compensation flag
    restricted: bool = False
    target: Optional[float] = None  # coach target override for restricted ROM blocks


def _protocol(n_correct: int, n_restricted: int, n_comp: int, unknown_s: float) -> list:
    b = [Block("rest", "rest", "unknown", "Rest calibration",
               "Stand relaxed, arms by your sides, look at the screen.", duration_s=5.0, correct=None)]
    for ex, name in (("flexion", "forward raise"), ("abduction", "side raise"), ("external_rotation", "outward rotation")):
        b.append(Block(f"{ex}_correct", "reps", ex, f"{name.capitalize()}: correct",
                       f"Do the {name} slowly, as far as comfortable, and hold at the top.", reps=n_correct))
    for ex, name, tgt in (("flexion", "forward raise", 80.0), ("abduction", "side raise", 75.0),
                          ("external_rotation", "outward rotation", 25.0)):
        b.append(Block(f"{ex}_restricted", "reps", ex, f"{name.capitalize()}: stiff shoulder",
                       f"Pretend your shoulder is stiff. Stop the {name} at about {tgt:.0f} degrees and hold.",
                       reps=n_restricted, restricted=True, target=tgt))
    for ex, comp, text in (
            ("flexion", "SHRUG", "Shrug your shoulder up toward your ear as you raise the arm forward."),
            ("abduction", "TRUNK_LEAN", "Lean your body sideways, away from the arm, as you raise it."),
            ("external_rotation", "ELBOW_DRIFT", "Let your elbow drift away from your side as you rotate."),
            ("flexion", "TOO_FAST", "Raise the arm quickly and drop it straight away. Do not hold.")):
        b.append(Block(f"{ex}_{comp.lower()}", "reps", ex, f"Mistake: {comp.replace('_', ' ').lower()}",
                       text, reps=n_comp, correct=False, comp=comp))
    b.append(Block("unknown", "timed", "unknown", "Everyday movements",
                   "Move naturally and follow the prompts. These are not exercises.",
                   duration_s=unknown_s, correct=None))
    return b


PROTOCOLS = {
    "full": lambda: _protocol(8, 5, 5, 120.0),
    "quick": lambda: _protocol(4, 3, 3, 60.0),
}


class DatasetRecorder:
    def __init__(self, root: Path = DEFAULT_ROOT, up_cam=(0.0, -1.0, 0.0)):
        self.root = Path(root)
        self.up_cam = tuple(float(v) for v in up_cam)
        self.active = False
        self.blocks: list = []
        self.idx = 0
        self._fh = None
        self._announce_id = 0
        self.announce: Optional[str] = None
        self.shrug_baseline: Optional[float] = None
        self.baseline_ready = False
        self.session_dir: Optional[Path] = None
        self.done = False

    # -- control --------------------------------------------------------------------------------
    def start(self, subject_id: str, side: str, consent: bool, protocol: str = "full",
              session_id: Optional[str] = None) -> dict:
        if not consent:
            raise ValueError("written consent is required before recording")
        if not SUBJECT_RE.match(subject_id or ""):
            raise ValueError("subject_id must be 1-16 letters, digits, _ or -")
        if side not in ("right", "left"):
            raise ValueError("side must be right|left")
        if protocol not in PROTOCOLS:
            raise ValueError(f"protocol must be one of {sorted(PROTOCOLS)}")
        if self.active:
            self.stop()
        self.subject_id, self.side, self.protocol = subject_id, side, protocol
        self.session_id = session_id or time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = self.root / subject_id / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.blocks = PROTOCOLS[protocol]()
        self.idx, self.active, self.done = 0, True, False
        self.shrug_baseline, self.baseline_ready = None, False
        self._fh = open(self.session_dir / "frames.jsonl", "a", encoding="utf-8")
        self._write_session()
        self._begin_block()
        return self.status()

    def next(self) -> dict:
        if self.active:
            self._finish_block(complete=False)
            self._advance(+1)
        return self.status()

    def prev(self) -> dict:
        """Discard the block in progress and redo the previous one (or restart the first)."""
        if self.active:
            self._advance(-1 if self.idx > 0 else 0)
        return self.status()

    def stop(self) -> dict:
        if self.active:
            self._finish_block(complete=False)
            self.active = False
            self._write_session()
            if self._fh:
                self._fh.close()
                self._fh = None
        return self.status()

    @property
    def block(self) -> Optional[Block]:
        return self.blocks[self.idx] if self.active and self.idx < len(self.blocks) else None

    # -- per frame ------------------------------------------------------------------------------
    def on_frame(self, t_ms: float, frame: int, kp3d: Optional[list], angles: Optional[dict], coach: dict,
                 up_cam) -> bool:
        """Record one frame. Returns True when the block changed (caller re-applies coach settings)."""
        b = self.block
        if b is None:
            return False
        if self._t0 is None:
            self._t0 = t_ms
        self._t_last = t_ms
        el = (t_ms - self._t0) / 1000.0
        prep = el < PREP_S
        phase = coach.get("state")
        rec = {
            "t_ms": t_ms, "frame": frame, "block": self.idx, "block_id": b.id, "prep": prep,
            "exercise": b.exercise, "correct": b.correct, "comp": b.comp, "restricted": b.restricted,
            "phase": phase, "rep_count": coach.get("rep_count", 0), "kp3d_cam": kp3d, "angles": angles,
        }
        self._fh.write(json.dumps(rec) + "\n")
        if not prep:
            rec["attempt"] = self._track_attempt(phase, int(coach.get("rep_count", 0)))
            self._buf.append(rec)
            if b.kind == "rest" and angles and (angles.get("shrug_index") or {}).get("value") is not None:
                self._shrug.append(angles["shrug_index"]["value"])
        if b.kind == "timed" and not prep:
            k = int((el - PREP_S) // UNKNOWN_PROMPT_S)
            if k != self._prompt_k:
                self._prompt_k = k
                self._prompt = UNKNOWN_PROMPTS[k % len(UNKNOWN_PROMPTS)]
                self._say(self._prompt)
        finished = (
            (b.kind in ("rest", "timed") and el >= PREP_S + b.duration_s)
            or (b.kind == "reps" and not prep and coach.get("rep_count", 0) >= b.reps))
        if finished:
            self._finish_block(complete=True)
            self._advance(+1)
            return True
        return False

    def status(self) -> dict:
        b = self.block
        out = {"active": self.active, "done": self.done, "announce": self.announce,
               "announce_id": self._announce_id}
        if not self.blocks:
            return out
        out.update({"subject_id": self.subject_id, "session_id": self.session_id, "side": self.side,
                    "protocol": self.protocol, "block_index": self.idx, "n_blocks": len(self.blocks),
                    "dir": str(self.session_dir)})
        if b is not None:
            out["block"] = asdict(b)
            out["frames"] = len(self._buf)
            out["prompt"] = self._prompt
            out["reps_done"] = self._reps_seen()
            if b.kind in ("rest", "timed") and self._t_last is not None and self._t0 is not None:
                out["remaining_s"] = round(max(0.0, PREP_S + b.duration_s - (self._t_last - self._t0) / 1000), 1)
        return out

    # -- internals ------------------------------------------------------------------------------
    def _reps_seen(self) -> int:
        return int(self._buf[-1]["rep_count"]) if self._buf else 0

    def _track_attempt(self, phase: Optional[str], rep_count: int) -> Optional[str]:
        """Label for the frame being added; frames of an open attempt stay None until it ends."""
        label = None
        if phase in _ACTIVE:
            if self._att_start is None:
                self._att_start, self._att_rc0 = len(self._buf), self._rc_prev
        else:
            if self._att_start is not None:
                outcome = "counted" if rep_count > self._att_rc0 else "rejected"
                for r in self._buf[self._att_start:]:
                    r["attempt"] = outcome
                self._att_start = None
            label = "paused" if phase == "paused" else "rest"
        self._rc_prev = rep_count
        return label

    def _begin_block(self) -> None:
        b = self.block
        self._att_start, self._att_rc0, self._rc_prev = None, 0, 0
        self._buf, self._shrug, self._t0, self._t_last, self._prompt_k = [], [], None, None, -1
        self._prompt = b.prompt
        what = f"{b.reps} reps" if b.kind == "reps" else f"{b.duration_s:.0f} seconds"
        self._say(f"Block {self.idx + 1} of {len(self.blocks)}: {b.title}. {b.prompt} {what}.")

    def _advance(self, step: int) -> None:
        self.idx += step
        if self.idx >= len(self.blocks):
            self.done = True
            self._say("Recording complete. Thank you!")
            self.stop()
            return
        self._begin_block()

    def _say(self, text: str) -> None:
        self.announce = text
        self._announce_id += 1

    def _finish_block(self, complete: bool) -> None:
        b = self.block
        if b is None or not self._buf:
            return
        if b.kind == "rest" and len(self._shrug) >= 15:
            self.shrug_baseline = float(np.median(self._shrug))
            self.baseline_ready = True
        pts = np.array([[[np.nan] * 3 if p is None else p for p in (r["kp3d_cam"] or [None] * 17)]
                        for r in self._buf], dtype=np.float32)
        phase = np.array([PHASE_INDEX.get(r["phase"], -1) for r in self._buf], dtype=np.int8)
        attempt = np.array([ATTEMPT_INDEX[r["attempt"] or "incomplete"] for r in self._buf], dtype=np.int8)
        np.savez_compressed(
            self.session_dir / f"{self.idx:02d}_{b.id}.npz",
            points=pts, t_ms=np.array([r["t_ms"] for r in self._buf]), phase=phase, attempt=attempt,
            rep_count=np.array([r["rep_count"] for r in self._buf], dtype=np.int16),
            exercise=b.exercise, side=self.side, correct=-1 if b.correct is None else int(b.correct),
            comp=b.comp or "", restricted=b.restricted, complete=complete, subject=self.subject_id,
            up_cam=np.asarray(self.up_cam, dtype=np.float32),
            shrug_baseline=np.nan if self.shrug_baseline is None else self.shrug_baseline)
        self._buf = []

    def _write_session(self) -> None:
        meta = {"subject_id": self.subject_id, "session_id": self.session_id, "side": self.side,
                "protocol": self.protocol, "consent": True, "hub_version": __version__,
                "shrug_baseline": self.shrug_baseline, "blocks": [asdict(b) for b in self.blocks],
                "fps_nominal": 30, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        (self.session_dir / "session.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
