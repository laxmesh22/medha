"""Claude only phrases answers from the station's measured session; without a credential the coach keeps fixed answers."""
import json
from types import SimpleNamespace

from physiobuddy_hub.coach_llm import MODEL, SYSTEM, CoachLLM, session_context


class FakeMessages:
    def __init__(self, stop="end_turn", text="You did 3 reps."):
        self.stop, self.text, self.sent = stop, text, None

    def create(self, **kw):
        self.sent = kw
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=self.text)])


def llm_with(messages):
    llm = CoachLLM()
    llm._client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return llm


def test_answers_from_the_live_session_only():
    fake = FakeMessages()
    state = {"coach": {"exercise": {"id": "flexion", "name": "Forward elevation (flexion)", "hold_s": 5.0},
                       "rep_count": 3, "correct_count": 2, "target": 120.0},
             "measure": {"source": "straps"}}
    out = llm_with(fake).ask("how am I doing?", session_context(state))
    assert out == {"ok": True, "text": "You did 3 reps.", "reason": None}
    assert fake.sent["model"] == MODEL and fake.sent["system"] == SYSTEM
    body = fake.sent["messages"][0]["content"]
    context = json.loads(body.split("\n", 1)[1].split("\n\nPatient said:")[0])
    assert context["coach"]["rep_count"] == 3 and context["measure"]["source"] == "straps"
    assert "never diagnose" in SYSTEM.lower() and "invent" in SYSTEM


def test_a_refusal_falls_back_to_the_fixed_answer():
    assert llm_with(FakeMessages(stop="refusal")).ask("hi", {})["ok"] is False


def test_no_credential_means_off():
    llm = CoachLLM()
    assert not llm.available and llm.provider is None and llm.ask("hi", {})["ok"] is False


class FakeHttp:
    def __init__(self, status=200, payload=None):
        self.status, self.payload, self.calls = status, payload, []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        return SimpleNamespace(status_code=self.status, json=lambda: self.payload)


def test_deepseek_answers_when_there_is_no_claude_key(monkeypatch):
    import httpx

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake = FakeHttp(payload={"choices": [{"message": {"content": "Two of your reps were correct."}}]})
    monkeypatch.setattr(httpx, "post", fake)
    llm = CoachLLM()
    assert llm.provider == "deepseek"
    out = llm.ask("how many were right?", {"coach": {"correct_count": 2}})
    assert out["ok"] and out["text"] == "Two of your reps were correct."
    url, kw = fake.calls[0]
    assert kw["json"]["messages"][0] == {"role": "system", "content": SYSTEM}
    assert '"correct_count":2' in kw["json"]["messages"][1]["content"]
    monkeypatch.setattr(httpx, "post", FakeHttp(status=500))
    assert llm.ask("again?", {})["ok"] is False


def test_sarvam_voice_caches_repeated_phrases(monkeypatch):
    import base64

    import httpx

    from physiobuddy_hub.coach_llm import SarvamVoice

    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    fake = FakeHttp(payload={"audios": [base64.b64encode(b"ID3mp3").decode()]})
    monkeypatch.setattr(httpx, "post", fake)
    voice = SarvamVoice()
    assert voice.speak("Good rep.") == b"ID3mp3" and voice.speak("Good rep.") == b"ID3mp3"
    assert len(fake.calls) == 1 and fake.calls[0][1]["json"]["language_code"] == "en-IN"
    monkeypatch.setattr(httpx, "post", FakeHttp(status=401))
    assert voice.speak("Keep your elbow straight.") is None          # the page then uses the browser voice
