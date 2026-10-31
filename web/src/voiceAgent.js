// Live voice coach. It watches the hub's coach verdicts (deterministic, measured) and talks to the
// patient: instant corrections, per-rep right/wrong, hold prompts, milestones. With the mic on it also
// answers spoken questions and commands. It never invents measurements and never gives medical advice;
// pain mentions trigger a fixed safety response (handoff design rules).
//
// Speech uses the browser (SpeechSynthesis + SpeechRecognition): Chrome/Edge. Recognition needs a
// secure context: http://localhost on the station itself, or HTTPS when used from a tablet.

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

const PRAISE = ['Good rep.', 'Nice and controlled.', 'That one was correct.', 'Well done.', 'Good form.'];
const pick = (arr, i) => arr[i % arr.length];

export class VoiceAgent {
  constructor({ log, onState, actions }) {
    this.log = log;               // (role, text, kind) -> UI transcript
    this.onState = onState;       // ('idle'|'listening'|'speaking'|'paused') -> UI orb
    this.actions = actions;       // { nextExercise, setPaused, context }
    this.voiceOn = false;
    this.micOn = false;
    this.paused = false;
    this.seen = new Set();
    this.lastSpoken = {};
    this.lastSaid = '';
    this.prevForm = 'idle';
    this.prevState = 'rest';
    this.primed = false;
    this.speaking = false;
    this.rec = null;
    this.micSupported = !!Recognition && (window.isSecureContext || location.hostname === 'localhost');
    this.serverVoice = false;
    this.audio = null;
    fetch('/api/agent/status').then((r) => r.json()).then((s) => { this.serverVoice = s.voice === 'sarvam'; }).catch(() => {});
  }

  // ------------------------------------------------------------------ output
  say(text, { priority = 1, key = text, minGapS = 0, kind = 'agent' } = {}) {
    const now = performance.now() / 1000;
    if (minGapS && now - (this.lastSpoken[key] || -1e9) < minGapS) return;
    this.lastSpoken[key] = now;
    this.lastSaid = text;
    this.log('agent', text, kind);
    if (!this.voiceOn) return;
    if (this.speaking && priority < 2) return; // don't talk over a correction with chatter
    this.stopSpeaking();
    if (this.serverVoice) { this.playServer(text); return; }
    this.browserSay(text);
  }

  stopSpeaking() {
    this.sayToken = (this.sayToken || 0) + 1;
    window.speechSynthesis?.cancel();
    if (this.audio) { this.audio.pause(); this.audio = null; }
  }

  // Sarvam voice from the station (Indian English); the browser voice if it fails.
  async playServer(text) {
    const token = this.sayToken;
    this.speaking = true;
    this.pauseListening();
    this.onState('speaking');
    try {
      const r = await fetch('/api/agent/speak', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
      });
      if (!r.ok) throw new Error(`speak ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      if (token !== this.sayToken) { URL.revokeObjectURL(url); return; }
      const a = new Audio(url);
      this.audio = a;
      const done = () => {
        URL.revokeObjectURL(url);
        if (token !== this.sayToken) return;
        this.audio = null;
        this.speaking = false;
        this.resumeListening();
        this.onState(this.micOn ? 'listening' : 'idle');
      };
      a.onended = done;
      a.onerror = done;
      await a.play();
    } catch {
      if (token === this.sayToken) { this.speaking = false; this.browserSay(text); }
    }
  }

  browserSay(text) {
    if (!('speechSynthesis' in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.0;
    u.lang = 'en-IN';
    u.onstart = () => { this.speaking = true; this.pauseListening(); this.onState('speaking'); };
    u.onend = u.onerror = () => { this.speaking = false; this.resumeListening(); this.onState(this.micOn ? 'listening' : 'idle'); };
    window.speechSynthesis.speak(u);
  }

  setVoice(on) {
    this.voiceOn = on;
    if (!on) this.stopSpeaking();
    else this.say('Voice coach on. I will tell you when a movement is right, and what to fix when it is not.', { priority: 2 });
  }

  // ------------------------------------------------------------------ watching
  observe(state, explain) {
    const c = state.coach;
    if (!c) return;
    // first message after connecting: history is already done, don't replay it
    if (!this.primed) {
      for (const ev of c.events || []) this.seen.add(`${ev.code}|${ev.text}`);
      this.primed = true;
      this.prevForm = c.form;
      this.prevState = c.state;
      return;
    }
    if (this.paused) return;
    // Say when the measurement moves between the camera and the worn bands.
    const src = state.measure?.source ?? null;
    if (this.prevSource !== undefined && src !== this.prevSource) {
      if (src === 'straps') this.say("I can't see your arm on the camera, so I am measuring with your bands.", { priority: 2, key: 'source', minGapS: 8 });
      else if (src === 'camera' && this.prevSource === 'straps') this.say('I can see you on the camera again.', { key: 'source', minGapS: 8 });
    }
    this.prevSource = src;
    // Camera and bands disagree: the rep is not counted, ask for a slower repeat (never average the two).
    if (c.cue?.code === 'LOW_QUALITY' && /disagree/.test(c.cue.text)) {
      this.say('The camera and your bands disagree. Please repeat that movement slowly.', { priority: 2, key: 'disagree', minGapS: 10, kind: 'warn' });
    }
    for (const ev of c.events || []) {
      const k = `${ev.code}|${ev.text}`;
      if (this.seen.has(k)) continue;
      this.seen.add(k);
      this.onEvent(ev, c);
    }
    // live correction the moment form goes wrong
    if (c.form === 'fix' && c.cue) {
      this.say(c.cue.text, { priority: 2, key: c.cue.code, minGapS: 6, kind: 'fix' });
    }
    if (c.state !== this.prevState) {
      if (c.state === 'hold') this.say(`Hold it there. ${Math.round(c.exercise.hold_s)} seconds.`, { key: 'hold', minGapS: 4 });
      if (this.prevState === 'hold' && c.hold_s >= c.exercise.hold_s * 0.7) this.say('Good hold. Lower slowly.', { key: 'holddone', minGapS: 4 });
    }
    if (c.cue?.code === 'TARGET') this.say('Target reached.', { key: 'target', minGapS: 8, kind: 'good' });
    this.prevForm = c.form;
    this.prevState = c.state;
  }

  onEvent(ev, c) {
    switch (ev.code) {
      case 'REP_GOOD': {
        const n = c.correct_count;
        const milestone = n > 0 && n % 5 === 0 ? ` That's ${n} correct reps.` : '';
        this.say(`${pick(PRAISE, n)} ${ev.text.replace(/^Rep (\d+) correct: /, 'Rep $1, ')}${milestone}`, { priority: 2, kind: 'good' });
        break;
      }
      case 'REP_FIX': this.say(ev.text, { priority: 2, kind: 'fix' }); break;
      case 'REP_REJECTED': this.say(ev.text, { priority: 2, kind: 'fix' }); break;
      case 'NO_MEASUREMENT': this.say("I can't see your arm clearly. Please step back into view.", { priority: 2, key: 'nomeas', minGapS: 10, kind: 'warn' }); break;
      case 'START': this.say(ev.text, { priority: 2 }); break;
      default: break;
    }
  }

  // ------------------------------------------------------------------ listening
  setMic(on) {
    if (!this.micSupported) {
      this.log('system', 'Voice input needs Chrome or Edge on the station itself (localhost) or HTTPS.', 'warn');
      return false;
    }
    this.micOn = on;
    if (on) {
      this.rec = new Recognition();
      this.rec.lang = 'en-IN';
      this.rec.continuous = true;
      this.rec.interimResults = false;
      this.rec.onresult = (e) => {
        const r = e.results[e.results.length - 1];
        if (r.isFinal) this.hear(r[0].transcript.trim());
      };
      this.rec.onend = () => { if (this.micOn && !this.speaking) this.safeStart(); };
      this.rec.onerror = (e) => { if (e.error === 'not-allowed') { this.micOn = false; this.log('system', 'Microphone permission was denied.', 'warn'); this.onState('idle'); } };
      this.safeStart();
      this.onState('listening');
      this.say('I am listening. Ask me how you are doing, or say next exercise.', { priority: 2 });
    } else {
      this.rec?.abort();
      this.rec = null;
      this.onState('idle');
    }
    return this.micOn;
  }

  safeStart() { try { this.rec?.start(); } catch { /* already started */ } }
  pauseListening() { try { this.rec?.abort(); } catch { /* noop */ } }
  resumeListening() { if (this.micOn) setTimeout(() => this.safeStart(), 250); }

  hear(text) {
    if (!text) return;
    this.log('user', text);
    const t = text.toLowerCase();
    const ctx = this.actions.context();
    const c = ctx.coach;
    // safety first: any pain mention stops the exercise with a fixed message
    if (/\b(pain|hurts?|hurting|sharp|numb|tingl|dizzy|chest)\b/.test(t)) {
      this.paused = true;
      this.actions.setPaused(true);
      this.say('Stop the exercise now and rest your arm. If the pain is sharp, does not settle, or you feel numbness or chest pain, contact your physiotherapist or doctor. I have paused the session.', { priority: 3, kind: 'warn' });
      this.onState('paused');
      return;
    }
    if (/\b(resume|start|begin|continue|go)\b/.test(t)) {
      this.paused = false;
      this.actions.setPaused(false);
      this.say(`Resuming ${c?.exercise?.name || 'the exercise'}. ${ctx.instructions || ''}`, { priority: 2 });
      return;
    }
    if (/\b(pause|stop|wait|break)\b/.test(t)) {
      this.paused = true;
      this.actions.setPaused(true);
      this.say('Paused. Say resume when you are ready.', { priority: 2 });
      this.onState('paused');
      return;
    }
    if (/\bnext\b/.test(t)) { this.actions.nextExercise(); return; }
    if (/(how many|count|reps?)\b/.test(t)) {
      this.say(`You have done ${c?.rep_count ?? 0} reps. ${c?.correct_count ?? 0} were correct.`, { priority: 2 });
      return;
    }
    if (/(how am i|how did i|doing|feedback|wrong|right)/.test(t)) {
      const last = c?.reps?.[c.reps.length - 1];
      if (!last) { this.say('No reps yet. Start when you are ready and I will judge each one.', { priority: 2 }); return; }
      this.say(last.correct ? `Your last rep was correct, ${Math.round(last.peak)} degrees.` : `Your last rep needed fixing: ${last.issues.join(', ')}.`, { priority: 2 });
      return;
    }
    if (/(best|highest|max)/.test(t)) {
      this.say(c?.best ? `Your best today is ${Math.round(c.best)} degrees.` : 'No completed reps yet.', { priority: 2 });
      return;
    }
    if (/(angle|degree|how high|how far)/.test(t)) {
      this.say(c?.value != null ? `You are at ${Math.round(c.value)} degrees. Target ${Math.round(c.target)}.` : 'I cannot measure right now. Please step into view.', { priority: 2 });
      return;
    }
    if (/target/.test(t)) { this.say(`Your target is ${Math.round(c?.target ?? 0)} degrees, set by your physiotherapist.`, { priority: 2 }); return; }
    if (/(muscle|working|stretch)/.test(t)) {
      const e = ctx.explain;
      this.say(e?.working?.length ? `Working now: ${e.working.slice(0, 3).join(', ')}.${e.stretching ? ` Stretching the ${e.stretching}.` : ''}` : 'Your arm is resting, so no muscles are working hard right now.', { priority: 2 });
      return;
    }
    if (/(repeat|again|what did you say|sorry)/.test(t)) { this.say(this.lastSaid || 'Nothing to repeat yet.', { priority: 2 }); return; }
    this.askClaude(text, ctx);
  }

  // Anything the fixed answers don't cover goes to Claude on the station, which sees only the measured session.
  // Safety (pain, stop, pause) is handled above and never reaches it.
  async askClaude(text, ctx) {
    const fallback = 'I can help with this exercise. Ask how many reps, how am I doing, my best, or say next exercise. For medical questions, please ask your physiotherapist.';
    try {
      const r = await fetch('/api/agent/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, explain: ctx.explain || null }),
      }).then((x) => x.json());
      if (r.ok && r.text) { this.say(r.text, { priority: 2 }); return; }
    } catch { /* station unreachable: fixed answer */ }
    this.say(fallback, { priority: 2 });
  }
}
