"""Rule-based exercise coach: rep phases, hold timer, peak angle, compensation cues, live narration.

Design rules (handoff §0 / §9.5):
* Works only on measured angles. If the metric is unavailable the coach PAUSES (never invents a value).
* Targets/holds come from the exercise definition (clinician-owned). The UI slider is a demo override.
* Deterministic + explainable: every cue has a reason code; this is what the "AI narration" shows.

Exercise definitions here are DRAFTS for the showcase and need physiotherapist approval.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

REST, RAISING, HOLD, LOWERING, PAUSED = "rest", "raising", "hold", "lowering", "paused"


@dataclass
class ExerciseDef:
    id: str
    name: str
    metric: str                 # key in CameraAngles.to_dict(): elevation | rotation
    target: float               # degrees (clinician-defined; demo default)
    hold_s: float
    movement: Optional[str]     # expected movement label from skeleton_kin (None = any)
    start_thr: float            # metric above this = rep started
    min_amplitude: float        # rep only counts if peak - start >= this
    watch_flags: tuple = ()     # compensation flags that matter for this exercise
    instructions: str = ""


EXERCISES = {
    "flexion": ExerciseDef(
        "flexion", "Forward elevation (flexion)", "elevation", 120.0, 5.0, "flexion", 25.0, 30.0,
        ("TRUNK_LEAN_SAGITTAL", "APPARENT_TRUE_GAP", "SHRUG"),
        "Raise the arm forward, thumb up, as far as comfortable. Stretch to tension, not pain."),
    "abduction": ExerciseDef(
        "abduction", "Side elevation (abduction)", "elevation", 110.0, 5.0, "abduction", 25.0, 30.0,
        ("TRUNK_LEAN_LATERAL", "APPARENT_TRUE_GAP", "SHRUG"),
        "Raise the arm out to the side, palm forward. Keep the trunk upright."),
    "external_rotation": ExerciseDef(
        "external_rotation", "External rotation (elbow at side)", "rotation", 45.0, 5.0, None, 10.0, 15.0,
        ("ELBOW_DRIFT", "TRUNK_LEAN_LATERAL", "SHRUG"),
        "Elbow bent 90° and tucked at your side. Rotate the forearm outward."),
}

CUE_TEXT = {
    "NO_MEASUREMENT": "Measurement unavailable: {reason}. Coach paused.",
    "USER_PAUSED": "Paused. Say resume when you are ready.",
    "USER_RESUMED": "Resumed. Start from rest.",
    "LOW_QUALITY": "Tracking is unreliable right now: {reason}. Not counting this moment.",
    "REP_LOW_QUALITY": "Not counted: tracking was unreliable for {pct:.0f}% of that rep.",
    "REP_NN_UNKNOWN": "Not counted: that did not look like an exercise movement.",
    "REP_NN_PHASE": "Not counted: no clear raise was seen.",
    "AUTO_EXERCISE": "Switched to {name}: that is the movement you are doing.",
    "START": "Begin: {instructions}",
    "HIGHER": "A little more if comfortable: {gap:.0f}° to your target.",
    "TARGET": "Target reached. Hold steady.",
    "HOLDING": "Hold… {remaining:.0f} s",
    "HOLD_DONE": "Hold complete. Lower slowly.",
    "LOWER": "Lower slowly and with control.",
    "REP_GOOD": "Rep {n} correct: {peak:.0f}°, held {hold:.1f} s.",
    "REP_FIX": "Rep {n} needs fixing: {issues}.",
    "REP_REJECTED": "Not counted: that was {seen}, this exercise is {expected}.",
    "TRUNK_LEAN_SAGITTAL": "Keep your trunk upright: you are leaning forward/back.",
    "TRUNK_LEAN_LATERAL": "Keep your trunk upright: you are leaning sideways.",
    "APPARENT_TRUE_GAP": "Body lean is adding fake range. Move from the shoulder.",
    "SHRUG": "Relax your shoulder down: avoid shrugging.",
    "ELBOW_DRIFT": "Keep your elbow tucked at your side.",
    "WRONG_MOVEMENT": "That looks like {seen}. This exercise is {expected}.",
}


# Plain-language reasons for a "needs fixing" verdict (spoken by the voice agent).
ISSUE_TEXT = {
    "TRUNK_LEAN_SAGITTAL": "your trunk leaned forward or back",
    "TRUNK_LEAN_LATERAL": "your trunk leaned sideways",
    "APPARENT_TRUE_GAP": "body lean added fake range",
    "SHRUG": "your shoulder shrugged up",
    "ELBOW_DRIFT": "your elbow moved away from your side",
    "TRUNK_LEAN": "your trunk leaned",
    "TOO_FAST": "the movement was too fast",
}
# PB-MotionNet compensation flags that may add to a rep verdict (SHORT_ROM never does: range is the
# clinician's call). Value = rule flags that already cover it.
NN_FLAG_RULES = {"SHRUG": ("SHRUG",), "TRUNK_LEAN": ("TRUNK_LEAN_SAGITTAL", "TRUNK_LEAN_LATERAL"),
                 "ELBOW_DRIFT": ("ELBOW_DRIFT",), "TOO_FAST": ()}
NN_MIN_FRAMES = 5            # network judgements needed inside a rep before it can veto
NN_UNKNOWN_MAJORITY = 0.5
# A hold counts if it reaches this share of the prescribed hold time.
HOLD_PASS_FRACTION = 0.7
# A rep is rejected if more than this share of its frames had low-quality measurements.
MAX_LOW_QUALITY_FRACTION = 0.2


@dataclass
class Rep:
    n: int
    peak: float
    hold_s: float
    reached_target: bool
    flags: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    nn_flags: list = field(default_factory=list)

    @property
    def correct(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {"n": self.n, "peak": round(self.peak, 1), "hold_s": round(self.hold_s, 1),
                "reached_target": self.reached_target, "flags": self.flags, "nn_flags": self.nn_flags,
                "correct": self.correct, "issues": self.issues}


class Coach:
    def __init__(self, exercise: str = "flexion", velocity_tau_s: float = 0.25,
                 hold_speed_dps: float = 8.0):
        self.tau = velocity_tau_s
        self.hold_speed = hold_speed_dps
        self.events: deque = deque(maxlen=12)
        self.user_paused = False
        self.set_exercise(exercise)

    # -- control -----------------------------------------------------------------------------
    def set_exercise(self, exercise_id: str, target: Optional[float] = None) -> None:
        if exercise_id not in EXERCISES:
            raise ValueError(f"unknown exercise {exercise_id}")
        self.ex = EXERCISES[exercise_id]
        self.target = float(target) if target is not None else self.ex.target
        self.reset()
        self._event("START", instructions=self.ex.instructions)

    def set_target(self, target: float) -> None:
        self.target = float(target)

    def set_paused(self, paused: bool) -> None:
        """Patient/clinician pause (pain, "stop"). The rep in progress is discarded, never counted."""
        paused = bool(paused)
        if paused == self.user_paused:
            return
        self.user_paused = paused
        self.state = PAUSED if paused else REST
        self._peak, self._hold_t, self._hold_start = 0.0, 0.0, None
        self._rep_flags, self._peak_movement = set(), None
        self._rep_frames = self._rep_low_frames = 0
        self._reset_nn_rep()
        self._t_prev, self._prev_val, self._v = None, None, 0.0
        self._event("USER_PAUSED" if paused else "USER_RESUMED")

    def _reset_nn_rep(self) -> None:
        self._nn_frames = self._nn_unknown = self._nn_active = 0
        self._nn_comp_max: dict = {}

    def reset(self) -> None:
        self.state = REST
        self.reps: list = []
        self._t_prev: Optional[float] = None
        self._v = 0.0
        self._prev_val: Optional[float] = None
        self._peak = 0.0
        self._start_val = 0.0
        self._hold_t = 0.0
        self._hold_start: Optional[float] = None
        self._rep_flags: set = set()
        self._peak_movement: Optional[str] = None
        self._rep_frames = 0
        self._rep_low_frames = 0
        self._reset_nn_rep()
        self.nn: Optional[dict] = None
        self._t_any: Optional[float] = None
        self._last_cue_t: dict = {}
        self.cue: Optional[dict] = None
        if self.user_paused:
            self.state = PAUSED

    # -- main update ---------------------------------------------------------------------------
    def update(self, t_s: float, angles: Optional[dict], nn: Optional[dict] = None) -> dict:
        """``nn``: latest PB-MotionNet judgement (``MotionNetRunner.push``) or None for rules-only."""
        t_any, self._t_any = self._t_any, t_s
        self.nn = nn
        if self.user_paused:
            self.state = PAUSED
            self.cue = self._cue("USER_PAUSED", t_s, priority=3)
            return self.snapshot()
        m = (angles or {}).get(self.ex.metric) or {}
        val = m.get("value")
        if val is not None and m.get("quality") == "low":
            # Unreliable geometry: show the number, but freeze the rep state machine on it.
            if self.state in (RAISING, HOLD, LOWERING):
                self._rep_frames += 1
                self._rep_low_frames += 1
            if self.state == HOLD and self._hold_start is not None and t_any is not None:
                self._hold_start += max(0.0, t_s - t_any)  # low-quality time never counts as hold
            self.cue = self._cue("LOW_QUALITY", t_s, priority=2,
                                 reason=m.get("reason") or "implausible body geometry")
            return self.snapshot(float(val))
        if val is None:
            reason = m.get("reason") or "person not tracked"
            if self.state != PAUSED:
                self._event("NO_MEASUREMENT", reason=reason)
            self.state = PAUSED
            self.cue = self._cue("NO_MEASUREMENT", t_s, priority=3, reason=reason)
            self._t_prev, self._prev_val = None, None
            return self.snapshot()

        val = float(val)  # plain floats only: snapshots are sent as JSON
        if self.state == PAUSED:
            self.state = REST if val < self.ex.start_thr else RAISING
        # smoothed angular velocity (deg/s)
        if self._t_prev is not None and t_s > self._t_prev:
            dt = t_s - self._t_prev
            a = dt / (self.tau + dt)
            self._v += a * ((val - self._prev_val) / dt - self._v)
        self._t_prev, self._prev_val = t_s, val

        flags = [f for f in (angles.get("flags") or []) if f in self.ex.watch_flags]
        self.cue = None
        prev_peak = self._peak
        self._step_state(t_s, val)
        if self.state in (RAISING, HOLD) and (val >= prev_peak or self._peak_movement is None):
            self._peak_movement = angles.get("movement")  # movement label at the top of the rep
        if self.state in (RAISING, HOLD, LOWERING):
            self._rep_flags.update(flags)
            self._rep_frames += 1
            if nn and nn.get("can_veto") is True:   # unvalidated models are display-only
                self._nn_frames += 1
                self._nn_unknown += bool(nn.get("is_unknown"))
                self._nn_active += nn.get("phase") in (RAISING, HOLD)
                for f, p in (nn.get("comp_probs") or {}).items():
                    self._nn_comp_max[f] = max(self._nn_comp_max.get(f, 0.0), float(p))

        # cue priority: compensation > wrong movement > progress
        if flags:
            self.cue = self._cue(flags[0], t_s, priority=2)
        elif (self.ex.movement and self.state == RAISING and angles.get("movement")
              and angles["movement"] not in (self.ex.movement, "rest")):
            self.cue = self._cue("WRONG_MOVEMENT", t_s, priority=1, seen=angles["movement"],
                                 expected=self.ex.movement)
        elif self.cue is None:
            self.cue = self._progress_cue(t_s, val)
        return self.snapshot(val)

    def _step_state(self, t_s: float, val: float) -> None:
        ex = self.ex
        if self.state == REST:
            if val >= ex.start_thr and self._v > 0:
                self.state = RAISING
                self._start_val = min(val, ex.start_thr)
                self._peak, self._hold_t, self._hold_start = val, 0.0, None
                self._rep_flags = set()
                self._peak_movement = None
                self._rep_frames = self._rep_low_frames = 0
                self._reset_nn_rep()
        elif self.state == RAISING:
            self._peak = max(self._peak, val)
            if abs(self._v) < self.hold_speed and val > ex.start_thr + ex.min_amplitude * 0.5:
                self.state, self._hold_start = HOLD, t_s
            elif self._v < -self.hold_speed and val < self._peak - 8:
                self.state = LOWERING
        elif self.state == HOLD:
            self._peak = max(self._peak, val)
            self._hold_t = t_s - (self._hold_start or t_s)
            if val < self._peak - 10 or self._v < -2 * self.hold_speed:
                self.state = LOWERING
                if self._hold_t >= ex.hold_s:
                    self._event("HOLD_DONE")
            elif self._v > 2 * self.hold_speed:
                self.state = RAISING  # moved further up: keep raising
        elif self.state == LOWERING:
            if val < ex.start_thr:
                self._finish_rep()
                self.state = REST
            elif self._v > 2 * self.hold_speed and val > self._peak - 5:
                self.state = RAISING

    def _finish_rep(self) -> None:
        if self._peak - self._start_val < self.ex.min_amplitude:
            return  # too small to count (fidget, not a rep)
        seen = self._peak_movement
        if self.ex.movement and seen not in (None, self.ex.movement, "rest"):
            self._event("REP_REJECTED", seen=seen, expected=self.ex.movement)
            return  # wrong movement pattern: correctness first
        if self._rep_frames and self._rep_low_frames / self._rep_frames > MAX_LOW_QUALITY_FRACTION:
            self._event("REP_LOW_QUALITY", pct=100.0 * self._rep_low_frames / self._rep_frames)
            return
        nn_flags = []
        if self._nn_frames >= NN_MIN_FRAMES:
            # hybrid agreement: the rule cycle completed, now the network must agree it was an exercise rep
            if self._nn_unknown / self._nn_frames > NN_UNKNOWN_MAJORITY:
                self._event("REP_NN_UNKNOWN")
                return
            if self._nn_active == 0:
                self._event("REP_NN_PHASE")
                return
            thr = float((self.nn or {}).get("comp_threshold", 0.7))
            nn_flags = sorted(f for f, p in self._nn_comp_max.items()
                              if p >= thr and f in NN_FLAG_RULES and self._nn_flag_relevant(f))
        flags = sorted(self._rep_flags)
        issues = [ISSUE_TEXT[f] for f in flags if f in ISSUE_TEXT]
        for f in nn_flags:
            if not any(r in flags for r in NN_FLAG_RULES[f]):  # the rules did not already say so
                issues.append(ISSUE_TEXT[f])
        if self._hold_t < self.ex.hold_s * HOLD_PASS_FRACTION:
            issues.append(f"held {self._hold_t:.1f} of {self.ex.hold_s:.0f} seconds")
        rep = Rep(len(self.reps) + 1, float(self._peak), float(self._hold_t),
                  bool(self._peak >= self.target - 5), flags, issues, nn_flags)
        self.reps.append(rep)
        if rep.correct:
            self._event("REP_GOOD", n=rep.n, peak=rep.peak, hold=rep.hold_s)
        else:
            self._event("REP_FIX", n=rep.n, issues=", ".join(issues))

    def _nn_flag_relevant(self, f: str) -> bool:
        if f == "TOO_FAST":
            return True
        return any(r in self.ex.watch_flags for r in NN_FLAG_RULES[f])

    def _progress_cue(self, t_s: float, val: float) -> Optional[dict]:
        gap = self.target - val
        if self.state == RAISING:
            return self._cue("TARGET" if gap <= 5 else "HIGHER", t_s, priority=0, gap=gap)
        if self.state == HOLD:
            remaining = self.ex.hold_s - self._hold_t
            if remaining > 0:
                return self._cue("HOLDING", t_s, priority=0, remaining=max(remaining, 0))
            return self._cue("HOLD_DONE", t_s, priority=0)
        if self.state == LOWERING:
            return self._cue("LOWER", t_s, priority=0)
        return None

    # -- helpers -------------------------------------------------------------------------------
    def _cue(self, code: str, t_s: float, priority: int, **kw) -> dict:
        text = CUE_TEXT[code].format(**kw)
        speak = t_s - self._last_cue_t.get(code, -1e9) > 6.0  # don't repeat the same voice cue < 6 s
        if speak:
            self._last_cue_t[code] = t_s
        return {"code": code, "text": text, "priority": priority, "speak": speak}

    def _event(self, code: str, extra: str = "", **kw) -> None:
        self.events.append({"code": code, "text": CUE_TEXT[code].format(**kw) + extra})

    def _form(self) -> tuple:
        """Live verdict while moving: idle | good | fix | paused (+ reasons)."""
        if self.state == PAUSED:
            return "paused", []
        if self.cue and self.cue["code"] == "LOW_QUALITY":
            return "paused", [self.cue["text"]]
        if self.cue and self.cue["code"] in ISSUE_TEXT:
            return "fix", [ISSUE_TEXT[self.cue["code"]]]
        if self.cue and self.cue["code"] == "WRONG_MOVEMENT":
            return "fix", [self.cue["text"]]
        return ("good" if self.state in (RAISING, HOLD, LOWERING) else "idle"), []

    def snapshot(self, val: Optional[float] = None) -> dict:
        form, form_issues = self._form()
        return {
            "form": form,
            "form_issues": form_issues,
            "correct_count": sum(r.correct for r in self.reps),
            "exercise": {"id": self.ex.id, "name": self.ex.name, "metric": self.ex.metric,
                         "hold_s": self.ex.hold_s},
            "target": self.target,
            "state": self.state,
            "user_paused": self.user_paused,
            "value": None if val is None else round(val, 1),
            "velocity_dps": round(self._v, 1),
            "peak": round(self._peak, 1) if self.state in (RAISING, HOLD, LOWERING) else None,
            "hold_s": round(self._hold_t, 1) if self.state in (HOLD, LOWERING) else 0.0,
            "progress": None if val is None else round(max(0.0, min(1.0, val / self.target)), 3),
            "reps": [r.to_dict() for r in self.reps[-10:]],
            "rep_count": len(self.reps),
            "best": round(max((r.peak for r in self.reps), default=0.0), 1) or None,
            "cue": self.cue,
            "events": list(self.events),
            "nn": self.nn,
        }
