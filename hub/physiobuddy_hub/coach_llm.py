"""Spoken answers to the patient's free questions, and the coach's voice, grounded in the live session.

Handoff §9.6: the language model only phrases and explains. It never measures, judges a rep, diagnoses, prescribes,
or changes a target; the rule coach and the geometry do that. Every number it may say is in the context built here
from the station's own state.

Answers: Claude when a Claude credential exists (ANTHROPIC_API_KEY or an `ant auth login` profile), else DeepSeek
(team choice, handoff §0), else off and the voice coach keeps its fixed answers. Voice: Sarvam text-to-speech (Indian
English and Indian languages), else the page uses the browser's voice. Keys come from the environment or the
git-ignored hub/llm_keys.local.json.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import ssl
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_MODEL = "bulbul:v3"
KEYS_FILE = Path(__file__).resolve().parents[1] / "llm_keys.local.json"


def load_keys() -> dict:
    """Environment first, then the git-ignored key file. Missing keys are simply absent."""
    keys = {}
    try:
        keys.update({k: v for k, v in json.loads(KEYS_FILE.read_text(encoding="utf-8")).items() if v})
    except (OSError, ValueError):
        pass
    for env, name in (("DEEPSEEK_API_KEY", "deepseek_api_key"), ("SARVAM_API_KEY", "sarvam_api_key")):
        if os.environ.get(env):
            keys[name] = os.environ[env]
    return keys


def _tls() -> ssl.SSLContext:
    """The Windows certificate store: this laptop's Python bundle does not trust the network's certificates."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()
SYSTEM = """You are the voice of Auri, a shoulder rehabilitation coach at a clinic station. The patient is doing an \
exercise their physiotherapist prescribed. Your answer is spoken aloud by a speech synthesiser.

Rules, in order of importance:
1. Safety. If the patient mentions pain, numbness, tingling, dizziness or chest symptoms, tell them to stop and rest, \
and to contact their physiotherapist or doctor if it is sharp or does not settle. Do not continue the exercise.
2. Never diagnose, never name a condition, never suggest medication, and never change the exercise, the number of \
reps, or the target. Those belong to the physiotherapist; say so if asked.
3. Only use numbers that appear in the LIVE SESSION data. If a value is null or missing, say it is not measured right \
now. Never estimate, round up, or invent an angle, a count or a time.
4. "measure.source" says what measured the arm: "camera", "straps" (the worn bands), or null (nothing could). Say the \
bands when the source is straps.
5. Speak plainly to an older adult: at most two short sentences, no lists, no markdown, no emojis.
"""


def _prompt(context: dict, question: str) -> str:
    return f"LIVE SESSION (JSON):\n{json.dumps(context, separators=(',', ':'))}\n\nPatient said: {question}"


class CoachLLM:
    def __init__(self) -> None:
        self._client = None
        self._deepseek_key: Optional[str] = None
        self.reason: Optional[str] = None
        try:
            import anthropic

            self._anthropic = anthropic
            client = anthropic.Anthropic(timeout=15.0, max_retries=1,
                                         http_client=anthropic.DefaultHttpxClient(verify=_tls()))
            # The client is built without a credential and only fails when it sends; check up front.
            if any(getattr(client, a, None) for a in ("api_key", "auth_token", "credentials")):
                self._client = client
        except Exception as exc:  # no SDK
            log.info("Claude SDK unavailable: %s", exc)
        if self._client is None:
            self._deepseek_key = load_keys().get("deepseek_api_key")
        if not self.available:
            self.reason = "no language model configured: set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY"

    @property
    def available(self) -> bool:
        return self._client is not None or self._deepseek_key is not None

    @property
    def provider(self) -> Optional[str]:
        return "claude" if self._client is not None else ("deepseek" if self._deepseek_key else None)

    @property
    def model(self) -> Optional[str]:
        return {"claude": MODEL, "deepseek": DEEPSEEK_MODEL}.get(self.provider)

    def ask(self, question: str, context: dict) -> dict:
        if not self.available:
            return {"ok": False, "reason": self.reason}
        question = (question or "").strip()[:500]
        if not question:
            return {"ok": False, "reason": "empty question"}
        if self._client is None:
            return self._ask_deepseek(question, context)
        a = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM,
                output_config={"effort": "low"},          # short spoken answers; latency matters
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",                        # a policy decline is retried server-side
                messages=[{"role": "user", "content": _prompt(context, question)}],
            )
        except a.AuthenticationError:
            return {"ok": False, "reason": "Claude credential rejected"}
        except a.RateLimitError:
            return {"ok": False, "reason": "Claude is busy, try again"}
        except a.APIStatusError as exc:
            log.warning("Claude error %s", exc.status_code)
            return {"ok": False, "reason": f"Claude error {exc.status_code}"}
        except a.APIConnectionError:
            return {"ok": False, "reason": "no connection to Claude"}
        if response.stop_reason == "refusal":
            return {"ok": False, "reason": "Claude declined"}
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        return {"ok": bool(text), "text": text, "reason": None if text else "empty answer"}

    def _ask_deepseek(self, question: str, context: dict) -> dict:
        import httpx

        try:
            r = httpx.post(DEEPSEEK_URL, timeout=15.0, verify=_tls(),
                           headers={"Authorization": f"Bearer {self._deepseek_key}"},
                           json={"model": DEEPSEEK_MODEL, "max_tokens": 300, "temperature": 0.2,
                                 "messages": [{"role": "system", "content": SYSTEM},
                                              {"role": "user", "content": _prompt(context, question)}]})
        except httpx.HTTPError as exc:
            return {"ok": False, "reason": f"no connection to DeepSeek: {type(exc).__name__}"}
        if r.status_code != 200:
            log.warning("DeepSeek error %s", r.status_code)
            return {"ok": False, "reason": f"DeepSeek error {r.status_code}"}
        try:
            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
        except (ValueError, KeyError, IndexError):
            return {"ok": False, "reason": "DeepSeek answer unreadable"}
        return {"ok": bool(text), "text": text, "reason": None if text else "empty answer"}


class SarvamVoice:
    """Text to speech for the coach. Short coaching phrases repeat a lot, so recent audio is kept in memory."""

    def __init__(self, cache_size: int = 64) -> None:
        self._key = load_keys().get("sarvam_api_key")
        self._cache: OrderedDict = OrderedDict()
        self._size = cache_size
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._key is not None

    def speak(self, text: str, language: str = "en-IN") -> Optional[bytes]:
        """MP3 bytes, or None when Sarvam is off or fails (the page then uses the browser's voice)."""
        text = (text or "").strip()[:1000]
        if not self.available or not text:
            return None
        key = (language, text)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        import httpx

        try:
            r = httpx.post(SARVAM_URL, timeout=10.0, verify=_tls(), headers={"api-subscription-key": self._key},
                           json={"text": text, "language_code": language, "model": SARVAM_MODEL,
                                 "output_audio_codec": "mp3"})
            audio = base64.b64decode(r.json()["audios"][0]) if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            audio = None
        if audio is None:
            log.warning("Sarvam text-to-speech failed")
            return None
        with self._lock:
            self._cache[key] = audio
            while len(self._cache) > self._size:
                self._cache.popitem(last=False)
        return audio


def session_context(state: Optional[dict], explain: Optional[dict] = None) -> dict:
    """The facts Claude may use: the station's own measurements and coach state, nothing else."""
    s = state or {}
    coach = s.get("coach") or {}
    straps = s.get("straps") or {}

    def values(angles):
        return {k: (v or {}).get("value") for k, v in (angles or {}).items() if isinstance(v, dict)}

    ex = coach.get("exercise") or {}
    from .core.coach import EXERCISES

    definition = EXERCISES.get(ex.get("id"))
    return {
        "exercise": {"name": ex.get("name"), "instructions": definition.instructions if definition else None,
                     "target_deg": coach.get("target"), "hold_s": ex.get("hold_s")},
        "coach": {k: coach.get(k) for k in ("state", "value", "peak", "hold_s", "rep_count", "correct_count",
                                            "best", "form", "form_issues", "user_paused")},
        "last_reps": [{k: r.get(k) for k in ("n", "peak", "hold_s", "correct", "issues")}
                      for r in (coach.get("reps") or [])[-3:]],
        "cue": (coach.get("cue") or {}).get("text"),
        "measure": s.get("measure"),
        "camera_deg": values(s.get("angles")),
        "bands_deg": values(straps.get("angles")),
        "bands_connected": [d.get("slot") for d in straps.get("devices") or [] if d.get("connected")],
        "muscles": explain or None,
    }
