import './style.css';
import * as THREE from 'three';
import { connectLive } from './live.js';
import { Stage } from './stage.js';
import { SkeletonOverlay } from './skeletonOverlay.js';
import { Avatar, MODELS, mirrorKeypoints } from './avatar.js';
import { ATTRIBUTION, LAYER_PRESETS, RealAnatomy } from './anatomy.js';
import { RomOverlay } from './rom.js';
import { AngleChart, PALETTE, renderPhase, renderReps, VisionPanel } from './hud.js';
import { VoiceAgent } from './voiceAgent.js';
import { fadeMaterial } from './tween.js';

const GUIDANCE = {
  OK: 'Tracking',
  NO_PERSON: 'Step into the camera view',
  MOVE_CLOSER: 'Step closer: about 2 to 2.5 m from the camera',
  MOVE_BACK: 'Step back: about 2 to 2.5 m from the camera',
  SHOULDERS_NOT_VISIBLE: 'Both shoulders need to be visible',
  HIPS_NOT_VISIBLE: 'Hips hidden: trunk measures unavailable',
  HEAD_NOT_VISIBLE: 'Head not visible',
  ARM_NOT_VISIBLE: 'Affected arm not visible',
};
const FLAGS = {
  TRUNK_LEAN_SAGITTAL: ['Trunk leaning forward or back', 'warn'],
  TRUNK_LEAN_LATERAL: ['Trunk leaning sideways', 'warn'],
  APPARENT_TRUE_GAP: ['Apparent range differs from true range', 'warn'],
  SHRUG: ['Shoulder shrug', 'warn'],
  ELBOW_DRIFT: ['Elbow drifting from the side', 'warn'],
  THORAX_FROM_GRAVITY: ['Hips hidden: reduced accuracy', 'info'],
  NO_THORAX: ['Shoulders not tracked', 'info'],
  IMPLAUSIBLE_UPPER_ARM: ['Tracking glitch: upper arm', 'info'],
  IMPLAUSIBLE_FOREARM: ['Tracking glitch: forearm', 'info'],
  IMPLAUSIBLE_SHOULDER_WIDTH: ['Tracking glitch: shoulders', 'info'],
};
const MOVEMENT = {
  flexion: 'Seen: forward raise', abduction: 'Seen: side raise', scaption: 'Seen: diagonal raise',
  extension: 'Seen: backward reach', rest: 'Arm at rest', other: 'Seen: arm raise',
};
const EXERCISE_ORDER = ['flexion', 'abduction', 'external_rotation'];

const $ = (s) => document.querySelector(s);
const stage = new Stage($('#scene'));
const points = new SkeletonOverlay(stage.scene);
const rom = new RomOverlay(stage.scene);
const vision = new VisionPanel($('#vision'), $('#video'));
const chart = new AngleChart($('#chart'));
points.visible = false;
$('#credit').textContent = ATTRIBUTION;
renderReps($('#rep-strip'), null);

const ui = { side: 'right', mirror: true, view: 'avatar', state: null, explain: null, exercises: {}, userPaused: false, lastRep: 0, repFlashUntil: 0 };
let avatar = null;
let anatomy = null;
let t = 0;
const displaySide = () => (ui.mirror ? (ui.side === 'right' ? 'left' : 'right') : ui.side);

// ---------------------------------------------------------------- transcript + voice agent
function log(role, text, kind = '') {
  const li = document.createElement('li');
  li.className = `${role === 'user' ? 'user' : role === 'system' ? 'system' : ''} ${kind}`.trim();
  const time = document.createElement('time');
  time.textContent = `${role === 'user' ? 'You' : role === 'system' ? 'System' : 'Coach'} · ${new Date().toTimeString().slice(0, 8)}`;
  li.append(time, document.createTextNode(text));
  const list = $('#transcript');
  list.prepend(li);
  while (list.children.length > 60) list.lastChild.remove();
}

const AGENT_STATE = { idle: 'Text only', listening: 'Listening', speaking: 'Speaking', paused: 'Paused by patient' };
const agent = new VoiceAgent({
  log,
  onState: (s) => {
    $('#orb').dataset.state = s;
    $('#agent-state').textContent = s === 'idle' && agent?.voiceOn ? 'Speaking enabled' : AGENT_STATE[s] || s;
  },
  actions: {
    context: () => ({
      coach: ui.state?.coach, explain: ui.explain,
      instructions: ui.exercises[ui.state?.coach?.exercise?.id]?.instructions,
    }),
    setPaused: (p) => setPaused(p),
    nextExercise: () => {
      const cur = ui.state?.coach?.exercise?.id || 'flexion';
      setExercise(EXERCISE_ORDER[(EXERCISE_ORDER.indexOf(cur) + 1) % EXERCISE_ORDER.length]);
    },
  },
});

// ---------------------------------------------------------------- models
let loadToken = 0;
function setLoading(frac, text) {
  const el = $('#loading');
  el.classList.toggle('done', frac >= 1);
  el.classList.toggle('bg', frac >= 0.4); // patient already visible: move to the corner
  $('#load-bar').style.width = `${Math.round(Math.min(frac, 1) * 100)}%`;
  if (text) $('#load-text').textContent = text;
}

async function loadModel(key) {
  const token = ++loadToken;
  setLoading(0, 'Loading patient model');
  try {
    const a = await Avatar.load(MODELS[key].url, { onProgress: (f) => setLoading(f * 0.4, 'Loading patient model') });
    if (token !== loadToken) return;
    if (avatar) avatar.root.removeFromParent();
    if (anatomy) anatomy.root.removeFromParent();
    avatar = a;
    anatomy = null;
    stage.scene.add(a.root);
    stage.setFloorY(a.footY);
    applyView(ui.view, 0);
    if (ui.state) render(ui.state);
    setLoading(0.4, 'Loading anatomy: bones, muscles, joint capsule');
    const an = await RealAnatomy.load(a.shoulderWidth(), (f) => setLoading(0.4 + f * 0.6));
    if (token !== loadToken) return;
    anatomy = an;
    stage.scene.add(an.root);
    applyView(ui.view, 0);
    setLoading(1);
    if (ui.state) render(ui.state);
  } catch (e) {
    console.warn('model load failed', e);
    setLoading(1);
    log('system', 'Could not load the 3D model. Showing camera points instead.', 'warn');
    if (!avatar) setView('points');
  }
}

function applyView(view, ms = 800) {
  points.visible = view === 'points' || !avatar;
  if (avatar) avatar.root.visible = view !== 'points' && view !== 'anatomy';
  rom.visible = view !== 'points' && !!avatar;
  $('#layers').hidden = view !== 'xray' && view !== 'anatomy';
  $('#explain').hidden = !(view === 'xray' || view === 'anatomy');
  const preset = LAYER_PRESETS[view] || LAYER_PRESETS.avatar;
  if (avatar) for (const m of avatar.skinMaterials) fadeMaterial(m, view === 'points' ? 1 : preset.skin, ms);
  if (anatomy) anatomy.setLayers(view === 'points' ? LAYER_PRESETS.avatar : preset, ms);
  document.querySelectorAll('#layers input').forEach((cb) => { cb.checked = preset[cb.dataset.layer] > 0.05; });
}

function setView(view) {
  ui.view = view;
  document.querySelectorAll('[data-view]').forEach((b) => b.classList.toggle('on', b.dataset.view === view));
  applyView(view);
}

// ---------------------------------------------------------------- live state
const fmt = (m) => (m && m.value != null ? `${Math.round(m.value)}°` : '--');

function setMetric(card, m) {
  card.querySelector('.val').textContent = fmt(m);
  card.dataset.quality = m ? m.quality : 'unavailable';
  // explicit "unavailable" with the reason: never show 0 for missing data
  card.querySelector('.note').textContent = !m ? '' : m.value === null ? (m.reason || 'unavailable') : m.quality === 'low' ? 'low quality' : '';
}

function renderVerdict(c) {
  const el = $('#verdict');
  const now = performance.now();
  let form = c?.form || 'idle', title = 'Ready', reason = 'Start the movement when you are ready';
  const last = c?.reps?.[c.reps.length - 1];
  if (last && last.n !== ui.lastRep) { ui.lastRep = last.n; ui.repFlashUntil = now + 2600; }
  if (ui.userPaused) { form = 'paused'; title = 'Paused'; reason = 'Say "resume" or press Speak to continue'; }
  else if (now < ui.repFlashUntil && last) {
    form = last.correct ? 'good' : 'fix';
    title = last.correct ? `Rep ${last.n} correct` : `Rep ${last.n}: fix this`;
    reason = last.correct ? `${Math.round(last.peak)}°, held ${last.hold_s.toFixed(1)} s` : last.issues.join(', ');
  } else if (form === 'good') { title = 'Correct form'; reason = c.state === 'hold' ? `Holding ${c.hold_s.toFixed(1)} s` : 'Keep going, smooth and controlled'; }
  else if (form === 'fix') { title = 'Fix your form'; reason = c.form_issues.join(', '); }
  else if (form === 'paused') { title = 'Cannot measure'; reason = c?.cue?.text?.replace(/ Coach paused\.$/, '') || 'Step into view'; }
  if (el.dataset.form !== form) { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); }
  el.dataset.form = form;
  $('#verdict-text').textContent = title;
  $('#verdict-reason').textContent = reason;
}

// ---------------------------------------------------------------- dataset recording drawer
let recAnnounceId = 0;
function renderRecorder(r) {
  const active = !!r?.active;
  $('#rec-form').hidden = active;
  $('#rec-live').hidden = !active;
  $('#rec-btn').textContent = active ? 'Recording…' : 'Record dataset';
  if (r?.announce_id && r.announce_id !== recAnnounceId) {
    recAnnounceId = r.announce_id;
    if (r.announce) agent.say(r.announce, { priority: 2, kind: 'system' });
  }
  if (!active || !r.block) return;
  const b = r.block;
  $('#rec-progress').textContent = `Block ${r.block_index + 1} of ${r.n_blocks} · ${r.subject_id} · ${r.side}`;
  $('#rec-title').textContent = b.title;
  $('#rec-prompt').textContent = r.prompt || b.prompt;
  $('#rec-count').textContent = b.kind === 'reps' ? `${r.reps_done} / ${b.reps} reps` : `${Math.ceil(r.remaining_s ?? b.duration_s)} s`;
  $('#rec-dir').textContent = `Saving to ${r.dir}`;
}

// ---------------------------------------------------------------- PB-MotionNet auto-detect
function renderAutodetect(ad, c) {
  const btn = $('#auto-btn');
  btn.hidden = !ad?.model_loaded;
  if (!ad?.model_loaded) return;
  const nn = c?.nn;
  const sees = !nn ? '' : nn.is_unknown ? ' · no exercise' : ` · ${ui.exercises[nn.predicted_exercise]?.name || nn.predicted_exercise} ${Math.round(nn.confidence * 100)}%`;
  // not validated on our recordings: show its opinion only, it cannot switch exercises or veto reps
  btn.disabled = !ad.available;
  btn.title = ad.available ? '' : 'Network not yet validated on Physio Buddy recordings: opinion only';
  btn.setAttribute('aria-pressed', String(!!ad.enabled));
  btn.classList.toggle('on', !!ad.enabled);
  btn.textContent = ad.available ? `Auto-detect${ad.enabled ? sees : ''}` : `Network (advisory)${sees}`;
  if (c?.exercise?.id) document.querySelectorAll('[data-ex]').forEach((b) => b.classList.toggle('on', b.dataset.ex === c.exercise.id));
}

function render(state) {
  ui.state = state;
  $('#fps').textContent = `${state.fps} fps · ${state.proc_ms} ms`;
  const g = state.guidance || [];
  const guide = $('#guidance');
  guide.textContent = g.map((c) => GUIDANCE[c] || c).join(' · ');
  guide.dataset.ok = g.length === 1 && g[0] === 'OK' ? 'yes' : 'no';

  const a = state.angles;
  const c = state.coach;
  const metricKey = c?.exercise?.metric || 'elevation';
  const m = a ? a[metricKey] : null;
  const readout = $('.readout');
  $('#ex-name').textContent = c?.exercise?.name || '';
  $('#movement').textContent = a ? (MOVEMENT[a.movement] || 'Tracking') : 'No person tracked';
  $('#elev').textContent = fmt(m);
  $('#elev-note').textContent = !m || m.value === null
    ? `Measurement unavailable${m?.reason ? `: ${m.reason}` : ''}`
    : `${metricKey === 'rotation' ? 'Rotation: outward +, inward −' : 'True elevation, arm against trunk'}${m.quality === 'low' ? ' · low quality' : ''}`;
  readout.dataset.quality = m ? m.quality : 'unavailable';
  const target = c?.target ?? 120;
  readout.classList.toggle('reached', m?.value != null && m.value >= target - 5);
  $('#rep-count').textContent = c?.rep_count ?? 0;
  $('#correct-count').textContent = c?.correct_count ?? 0;
  $('#progress-bar').style.transform = `scaleX(${c?.progress ?? 0})`;
  $('#hold-t').textContent = c?.state === 'hold' ? `${c.hold_s.toFixed(1)}s` : '';
  $('#best').textContent = c?.best ? `best ${Math.round(c.best)}°` : '';
  renderPhase($('#phase'), c);
  renderReps($('#rep-strip'), c);
  renderVerdict(c);
  chart.push(c);

  if (a) {
    document.querySelectorAll('.metric').forEach((card) => setMetric(card, a[card.dataset.key]));
    const box = $('#flags');
    box.innerHTML = '';
    for (const f of a.flags) {
      const [text, kind] = FLAGS[f] || [f, 'info'];
      const el = document.createElement('span');
      el.className = kind;
      el.textContent = text;
      box.appendChild(el);
    }
  }
  renderRecorder(state.recorder);
  renderAutodetect(state.autodetect, c);
  vision.update(state);
  agent.observe(state, ui.explain);

  const kp = ui.mirror ? mirrorKeypoints(state.keypoints) : state.keypoints;
  points.update(kp);
  if (avatar && state.keypoints) avatar.solve(kp);
  if (anatomy && state.keypoints) anatomy.solve(kp);
}

// per frame: smooth both rigs, then ROM overlay + anatomy highlights from the avatar's bones
const tmp = { a: new THREE.Vector3(), b: new THREE.Vector3(), c: new THREE.Vector3(), d: new THREE.Vector3() };
stage.onFrame.push((dt) => {
  t += dt;
  if (!avatar) return;
  avatar.step(dt);
  avatar.root.updateMatrixWorld(true);
  if (anatomy) anatomy.step(dt);
  const a = ui.state?.angles;
  const c = ui.state?.coach;
  const unavailable = !a || a.elevation.value === null;
  const A = avatar.armBones(displaySide());
  rom.target = c?.target ?? rom.target;
  rom.update({
    shoulder: avatar.worldPos(A.arm, tmp.a),
    elbow: avatar.worldPos(A.fore, tmp.b),
    trunkTop: avatar.worldPos(avatar.bones.neck, tmp.c),
    trunkBottom: avatar.worldPos(avatar.bones.hips, tmp.d),
    angles: a,
    colour: unavailable ? PALETTE.t3 : c?.form === 'fix' ? PALETTE.warn : PALETTE.accent,
  });
  if (anatomy) {
    ui.explain = anatomy.update(a, a?.flags || [], displaySide(), t);
    $('#working').textContent = ui.explain.working.length ? ui.explain.working.join(', ') : 'resting';
    $('#stretching').textContent = ui.explain.stretching || 'nothing yet';
  }
});

connectLive(render, (online) => {
  const el = $('#conn');
  el.className = `conn ${online ? 'on' : 'off'}`;
  el.querySelector('b').textContent = online ? 'Live' : 'Reconnecting';
  if (!online) { $('#guidance').textContent = 'Station offline: reconnecting'; $('#guidance').dataset.ok = 'no'; }
});

// ---------------------------------------------------------------- controls
async function api(path, body) {
  const r = await fetch(path, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  } : undefined);
  return r.json();
}

function setPaused(p) {
  ui.userPaused = p;
  // The hub must know too, or reps would keep counting while the patient is in pain.
  api('/api/coach/pause', { paused: p }).catch(() => log('system', 'Could not reach the hub to pause the coach.'));
}

async function setExercise(id) {
  const r = await api('/api/exercise', { id });
  if (!r.ok) return;
  document.querySelectorAll('[data-ex]').forEach((b) => b.classList.toggle('on', b.dataset.ex === id));
  $('#target').value = r.coach.target;
  $('#target-val').textContent = `${r.coach.target}°`;
  setPaused(false);
  agent.paused = false;
  agent.say(`Next: ${r.coach.exercise.name}. Target ${r.coach.target} degrees. ${ui.exercises[id]?.instructions || ''}`, { priority: 2 });
}

const savedModel = (() => { try { return localStorage.getItem('pb-model'); } catch { return null; } })();
$('#model').value = MODELS[savedModel] ? savedModel : 'female';
$('#model').addEventListener('change', (e) => {
  try { localStorage.setItem('pb-model', e.target.value); } catch { /* private mode */ }
  loadModel(e.target.value);
});
loadModel($('#model').value);

document.querySelectorAll('[data-ex]').forEach((b) => b.addEventListener('click', () => setExercise(b.dataset.ex)));
document.querySelectorAll('[data-side]').forEach((b) => b.addEventListener('click', async () => {
  ui.side = b.dataset.side;
  await api('/api/side', { side: ui.side });
  document.querySelectorAll('[data-side]').forEach((x) => x.classList.toggle('on', x === b));
}));
document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
document.querySelectorAll('#layers input').forEach((cb) => cb.addEventListener('change', () => {
  const on = cb.checked ? 1 : 0;
  if (cb.dataset.layer === 'skin' && avatar) {
    avatar.root.visible = true;
    for (const m of avatar.skinMaterials) fadeMaterial(m, on ? 0.14 : 0);
  } else if (anatomy) anatomy.setLayers({ [cb.dataset.layer]: on });
}));
$('#mirror').addEventListener('change', (e) => { ui.mirror = e.target.checked; });

let targetTimer;
$('#target').addEventListener('input', (e) => {
  $('#target-val').textContent = `${e.target.value}°`;
  clearTimeout(targetTimer);
  targetTimer = setTimeout(() => api('/api/target', { target: Number(e.target.value) }), 150);
});

const toggleRecDrawer = (open) => {
  $('#rec-drawer').hidden = !open;
  $('#rec-btn').setAttribute('aria-expanded', String(open));
};
$('#rec-btn').addEventListener('click', () => toggleRecDrawer($('#rec-drawer').hidden));
$('#auto-btn').addEventListener('click', () => api('/api/autodetect', { enabled: $('#auto-btn').getAttribute('aria-pressed') !== 'true' }));
$('#rec-close').addEventListener('click', () => toggleRecDrawer(false));
$('#rec-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const r = await api('/api/record/start', {
    subject_id: $('#rec-subject').value.trim(), side: ui.side,
    consent: $('#rec-consent').checked, protocol: $('#rec-protocol').value,
  });
  if (!r.ok) { log('system', `Recording not started: ${r.reason}`); return; }
  renderRecorder(r);
});
for (const action of ['prev', 'next', 'stop']) {
  $(`#rec-${action}`).addEventListener('click', async () => renderRecorder(await api(`/api/record/${action}`, {})));
}

$('#voice-btn').addEventListener('click', (e) => {
  const on = !agent.voiceOn;
  agent.setVoice(on);
  e.currentTarget.setAttribute('aria-pressed', String(on));
  if (on && ui.userPaused) { setPaused(false); agent.paused = false; }
  $('#agent-state').textContent = on ? 'Speaking enabled' : 'Text only';
});
$('#mic-btn').addEventListener('click', (e) => {
  const on = agent.setMic(!agent.micOn);
  e.currentTarget.setAttribute('aria-pressed', String(on));
});
document.querySelectorAll('[data-ask]').forEach((b) => b.addEventListener('click', () => agent.hear(b.dataset.ask)));

$('#rest-btn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = 'Stand relaxed, 2 s';
  try {
    const r = await fetch('/api/calibrate/rest?seconds=2', { method: 'POST' }).then((x) => x.json());
    btn.textContent = r.ok ? 'Rest baseline saved' : 'Calibration failed';
    log('system', r.ok ? 'Rest baseline captured. Shrug detection is now personalised.' : `Rest calibration failed: ${r.reason}. Stand still and try again.`, r.ok ? 'good' : 'warn');
  } catch {
    btn.textContent = 'Station offline';
  }
  setTimeout(() => { btn.textContent = 'Calibrate rest'; btn.disabled = false; }, 2500);
});

api('/api/exercises').then((list) => { for (const e of list) ui.exercises[e.id] = e; }).catch(() => {});
api('/api/status').then((s) => {
  ui.side = s.side || 'right';
  document.querySelectorAll('[data-side]').forEach((x) => x.classList.toggle('on', x.dataset.side === ui.side));
  $('#model-name').textContent = `${s.pose_model || 'pose'} + depth`;
  if (s.debug_video) {
    const btn = $('#video-btn');
    btn.hidden = false;
    btn.addEventListener('click', () => {
      const img = $('#video');
      img.hidden = !img.hidden;
      img.src = img.hidden ? '' : '/debug/stream.mjpg';
      btn.textContent = img.hidden ? 'Show video' : 'Hide video';
    });
  }
}).catch(() => log('system', 'Station status unavailable. Check the hub is running.', 'warn'));
log('system', 'Coach ready. Press Speak for voice feedback, Listen to talk to the coach.');
