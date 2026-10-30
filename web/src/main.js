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

// Same default as plan_items.pain_stop (clinician/supabase/schema.sql:101).
const PAIN_STOP = 6;
const PAIN_STOP_LINE = 'Please stop and rest. Tell your physiotherapist about this pain.';
const REJECT_CODES = new Set(['REP_REJECTED', 'REP_LOW_QUALITY', 'REP_NN_UNKNOWN', 'REP_NN_PHASE']);

// Page-session tallies. The hub resets reps when the exercise changes and only keeps the last 10,
// so this page copies what /ws/live already sends. Nothing is uploaded.
const session = {
  checkins: [],
  exercises: new Map(),
  lastEx: null,
  lastRepN: 0,
  prevEvents: [],
  primed: false,
};
let awaitingCheckin = true;

function eventKeys(events) {
  return (events || []).map((e) => `${e.code}|${e.text}`);
}

function freshEvents(prevKeys, events) {
  const keys = eventKeys(events);
  if (!prevKeys.length) return { keys, fresh: events || [] };
  for (let shift = 0; shift <= prevKeys.length; shift++) {
    const tail = prevKeys.slice(shift);
    const head = keys.slice(0, tail.length);
    if (tail.every((k, i) => k === head[i])) return { keys, fresh: (events || []).slice(tail.length) };
  }
  return { keys, fresh: [] };
}

function noteLive(state) {
  const c = state?.coach;
  if (!c?.exercise) return;
  const id = c.exercise.id;
  if (!session.primed) {
    session.primed = true;
    session.lastEx = id;
    session.lastRepN = c.rep_count || 0;
    session.prevEvents = eventKeys(c.events);
    return;
  }
  if (id !== session.lastEx) {
    session.lastEx = id;
    session.lastRepN = 0;
    session.prevEvents = eventKeys(c.events);
  }
  let bucket = session.exercises.get(id);
  if (!bucket) {
    bucket = { name: c.exercise.name, reps: [], rejected: [], best: null };
    session.exercises.set(id, bucket);
  } else bucket.name = c.exercise.name;
  if ((c.rep_count || 0) < session.lastRepN) session.lastRepN = 0;
  for (const r of c.reps || []) {
    if (r.n > session.lastRepN) bucket.reps.push({ peak: r.peak, issues: r.issues || [] });
  }
  session.lastRepN = Math.max(session.lastRepN, c.rep_count || 0);
  const turned = freshEvents(session.prevEvents, c.events);
  session.prevEvents = turned.keys;
  for (const ev of turned.fresh) {
    if (REJECT_CODES.has(ev.code)) bucket.rejected.push(ev.text);
  }
  const metric = state.angles?.[c.exercise.metric];
  if (metric && metric.value != null && Number.isFinite(metric.value)) {
    bucket.best = bucket.best == null ? metric.value : Math.max(bucket.best, metric.value);
  }
}

function resetPageSession() {
  session.checkins = [];
  session.exercises = new Map();
  session.lastEx = null;
  session.lastRepN = 0;
  session.prevEvents = [];
  session.primed = false;
  awaitingCheckin = true;
}

function fillSummary() {
  const root = $('#summary-body');
  root.replaceChildren();
  const since = document.createElement('p');
  since.className = 'rec-note';
  if (session.checkins.length) {
    const clock = session.checkins[0].at.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    since.textContent = `Since your pain check at ${clock}`;
  } else {
    since.textContent = 'No pain check yet.';
  }
  root.append(since);
  if (!session.exercises.size) {
    const p = document.createElement('p');
    p.className = 'rec-note';
    p.textContent = 'No exercise was measured in this session.';
    root.append(p);
  }
  for (const ex of session.exercises.values()) {
    const block = document.createElement('section');
    block.className = 'summary-ex';
    const h = document.createElement('h4');
    h.textContent = ex.name;
    const counted = document.createElement('p');
    counted.textContent = `Counted: ${ex.reps.length}`;
    const rejected = document.createElement('p');
    rejected.textContent = ex.rejected.length
      ? `Rejected: ${ex.rejected.length} — ${ex.rejected.join('; ')}`
      : 'Rejected: 0';
    const comps = [...new Set(ex.reps.flatMap((r) => r.issues))];
    block.append(h, counted, rejected);
    if (comps.length) {
      const comp = document.createElement('p');
      comp.textContent = `Compensations: ${comps.join('; ')}`;
      block.append(comp);
    }
    const best = document.createElement('p');
    best.className = 'deg';
    best.textContent = ex.best == null ? 'Best angle: unavailable' : `Best angle: ${Math.round(ex.best)}°`;
    block.append(best);
    root.append(block);
  }
  const painH = document.createElement('h4');
  painH.textContent = 'Pain check-ins';
  const list = document.createElement('ul');
  list.className = 'summary-pain';
  if (!session.checkins.length) {
    const li = document.createElement('li');
    li.textContent = 'No pain check-in.';
    list.append(li);
  } else {
    for (const c of session.checkins) {
      const li = document.createElement('li');
      const clock = c.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      li.textContent = c.stopped ? `${c.value} / 10 at ${clock} · stopped` : `${c.value} / 10 at ${clock}`;
      list.append(li);
    }
  }
  root.append(painH, list);
}
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
  const btn = $('#rec-btn');
  if (r && r.enabled === false) {
    btn.disabled = true;
    btn.textContent = 'Recording off';
    btn.title = r.reason || 'Recording is off: start the hub with --dataset-dir <folder>';
    $('#rec-drawer').hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    return;
  }
  btn.disabled = false;
  btn.title = '';
  const active = !!r?.active;
  $('#rec-form').hidden = active;
  $('#rec-live').hidden = !active;
  btn.textContent = active ? 'Recording…' : 'Record dataset';
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
  btn.title = ad.available ? '' : 'Network not yet validated on Auri recordings: opinion only';
  btn.setAttribute('aria-pressed', String(!!ad.enabled));
  btn.classList.toggle('on', !!ad.enabled);
  btn.textContent = ad.available ? `Auto-detect${ad.enabled ? sees : ''}` : `Network (advisory)${sees}`;
  if (c?.exercise?.id) document.querySelectorAll('[data-ex]').forEach((b) => b.classList.toggle('on', b.dataset.ex === c.exercise.id));
}

function render(state) {
  const preview = state.preview;
  if (preview) delete state.preview;
  ui.state = state;
  $('#fps').textContent = `${state.fps} fps · ${state.proc_ms} ms`;
  const g = state.guidance || [];
  const guide = $('#guidance');
  const hint = state.close_hint || (state.auri_cv && state.auri_cv.hint);
  guide.textContent = hint || g.map((c) => GUIDANCE[c] || c).join(' · ');
  guide.dataset.ok = !hint && g.length === 1 && g[0] === 'OK' ? 'yes' : 'no';

  const a = state.angles;
  const c = state.coach;
  const metricKey = c?.exercise?.metric || 'elevation';
  const m = a ? a[metricKey] : null;
  const readout = $('.readout');
  $('#ex-name').textContent = c?.exercise?.name || '';
  $('#movement').textContent = a ? (MOVEMENT[a.movement] || 'Tracking') : (hint ? 'Cannot measure' : 'No person tracked');
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
  noteLive(state);
  renderWebcam(state);
  renderStraps(state);
  renderRecorder(state.recorder);
  renderAutodetect(state.autodetect, c);
  vision.update(state, preview);
  agent.observe(state, ui.explain);

  const kp = ui.mirror ? mirrorKeypoints(state.keypoints) : state.keypoints;
  points.update(kp);
  const pose = state.strap_pose;
  if (avatar && pose && (pose.trunk || pose.upper_arm || pose.forearm)) {
    const flip = (v) => (!v || !ui.mirror ? v : [-v[0], v[1], v[2]]);
    avatar.solveStrap({
      side: pose.side,
      trunk: flip(pose.trunk),
      upper_arm: flip(pose.upper_arm),
      forearm: flip(pose.forearm),
    });
  } else if (avatar && state.keypoints) {
    avatar.solve(kp);
  }
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
  else if (awaitingCheckin) setPaused(true);
});

const STRAP_ROWS = [
  ['elevation', 'Elevation'],
  ['apparent_elevation', 'Apparent elevation'],
  ['plane_of_elevation', 'Plane'],
  ['elbow_flexion', 'Elbow bend'],
  ['rotation', 'Rotation'],
  ['trunk_lean_sagittal', 'Trunk lean, front/back'],
  ['trunk_lean_lateral', 'Trunk lean, sideways'],
];
const STRAP_CAL = { none: 'Not calibrated', npose: 'N-pose ok', raise: 'raise ok', 'npose+raise': 'N-pose and forward raise' };
const STRAP_SLOT_LABEL = { upper_arm: 'Upper arm', forearm: 'Forearm', trunk: 'Waist' };

function deg(m) {
  return m && m.value != null ? `${Math.round(m.value)}°` : 'unavailable';
}

function renderWebcam(state) {
  const card = $('#webcam-card');
  if (!state.auri_cv) { card.hidden = true; return; }
  card.hidden = false;
  const engine = state.auri_cv;
  const bits = [engine.quality || 'unavailable', engine.calibration || 'uncalibrated'];
  if (engine.torso_mode) bits.push(engine.torso_mode);
  $('#webcam-status').textContent = bits.join(' · ');
  const comp = engine.compensation;
  const reps = engine.rep_count == null ? 'unavailable' : String(engine.rep_count);
  $('#webcam-extra').textContent = comp
    ? `Reps ${reps} · ${engine.rep_state || 'unavailable'} · lean ${Math.round(comp.lateral_lean_deg)}° sideways, ${Math.round(comp.forward_lean_deg)}° forward`
    : `Reps ${reps} · ${engine.rep_state || 'unavailable'} · compensation unavailable`;
  const box = $('#webcam-compare');
  box.innerHTML = '';
  const hubElev = state.angles?.elevation;
  const rows = [
    ['Elevation', hubElev && hubElev.value != null ? `${Math.round(hubElev.value)}°` : 'unavailable', engine.elevation_deg],
    ['Flexion', 'unavailable', engine.flexion_deg],
    ['Abduction', 'unavailable', engine.abduction_deg],
    ['Display elevation', 'unavailable', engine.display_elevation_deg],
  ];
  for (const [label, camera, raw] of rows) {
    const row = document.createElement('div');
    row.className = 'metric';
    const strap = raw == null ? 'unavailable' : `${Math.round(raw)}°`;
    row.innerHTML = `<dt>${label}</dt><div class="strap-pair">`
      + `<div><span>Camera</span><b class="${camera === 'unavailable' ? 'missing' : ''}">${camera}</b></div>`
      + `<div><span>Engine</span><b class="${strap === 'unavailable' ? 'missing' : ''}">${strap}</b></div></div>`;
    box.appendChild(row);
  }
}

function renderStraps(state) {
  const card = $('#straps-card');
  if (!state.straps) { card.hidden = true; return; }
  card.hidden = false;
  const devs = state.straps.devices || [];
  const live = devs.filter((d) => d.connected);
  $('#straps-link').textContent = live.length
    ? live.map((d) => {
      const who = [d.name || d.address || 'strap', d.slot].filter(Boolean).join(' ');
      const fault = d.hardware ? ` · ${d.hardware}` : '';
      const hz = d.packet_rate_hz == null ? '' : ` · ${Math.round(d.packet_rate_hz)} Hz`;
      const bat = d.battery_pct == null ? ' · battery unavailable'
        : (d.battery_low ? ` · ${d.battery_pct}% · low battery` : ` · ${d.battery_pct}%`);
      return `${who} · connected${hz}${bat}${fault}`;
    }).join(' · ')
    : (state.straps.mode === 'phone' ? 'Waiting for the phone' : 'No strap connected');
  const cal = state.straps.calibration || { state: 'none', slots: [] };
  const sensors = (cal.sensors || []).join(', ');
  $('#straps-cal').textContent = `${STRAP_CAL[cal.state] || cal.state}${sensors ? ` · ${sensors}` : ''}`;
  const list = $('#straps-slots');
  list.innerHTML = '';
  const bySlot = {};
  for (const d of devs) if (d.slot) bySlot[d.slot] = d;
  for (const name of ['upper_arm', 'forearm', 'trunk']) {
    const row = document.createElement('li');
    const dev = bySlot[name];
    const slotCal = (cal.slots || []).find((s) => s.sensor === name);
    const mark = STRAP_CAL[slotCal?.state] || 'not calibrated';
    const who = dev
      ? `${dev.connected ? 'connected' : 'searching'}${dev.address ? ` · ${dev.address.slice(-5)}` : ''}`
      : 'no strap';
    row.innerHTML = `<span>${STRAP_SLOT_LABEL[name]}</span><b>${mark}</b><span>${who}</span>`;
    list.appendChild(row);
  }
  const box = $('#straps-compare');
  box.innerHTML = '';
  const cam = state.angles;
  const strap = state.straps.angles;
  for (const [key, label] of STRAP_ROWS) {
    const row = document.createElement('div');
    row.className = 'metric';
    const camM = cam?.[key];
    const stM = strap?.[key];
    const why = stM && stM.value == null && stM.reason ? stM.reason : '';
    row.innerHTML = `<dt>${label}</dt><div class="strap-pair">`
      + `<div><span>Camera</span><b class="${camM && camM.value != null ? '' : 'missing'}">${deg(camM)}</b></div>`
      + `<div><span>Strap</span><b class="${stM && stM.value != null ? '' : 'missing'}">${deg(stM)}</b></div></div>`
      + (why ? `<dd class="note">${why}</dd>` : '');
    box.appendChild(row);
  }
}

async function strapCalibrate(path, busy) {
  const msg = $('#straps-msg');
  const buttons = ['#straps-npose', '#straps-raise', '#straps-guided'].map((id) => $(id));
  buttons.forEach((b) => { b.disabled = true; });
  msg.hidden = false;
  msg.textContent = busy;
  let result;
  try {
    result = await fetch(path, { method: 'POST' }).then((r) => r.json());
  } catch {
    result = { ok: false, reason: 'Could not reach the station' };
  }
  buttons.forEach((b) => { b.disabled = false; });
  if (result.ok) { msg.hidden = true; msg.textContent = ''; return result; }
  msg.hidden = false;
  msg.textContent = result.reason || 'Calibration failed';
  return result;
}

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function guidedStraps() {
  const msg = $('#straps-msg');
  const buttons = ['#straps-npose', '#straps-raise', '#straps-guided'].map((id) => $(id));
  buttons.forEach((b) => { b.disabled = true; });
  msg.hidden = false;
  for (let i = 5; i >= 1; i -= 1) {
    msg.textContent = `Wear the sensors as they sit. Stand still, arms by your sides. Locking that position in ${i}`;
    await sleep(1000);
  }
  msg.textContent = 'Hold still…';
  let npose;
  try {
    npose = await fetch('/api/straps/calibrate/npose', { method: 'POST' }).then((r) => r.json());
  } catch {
    npose = { ok: false, reason: 'Could not reach the station' };
  }
  if (!npose.ok) {
    msg.textContent = npose.reason || 'N-pose was not accepted';
    buttons.forEach((b) => { b.disabled = false; });
    return;
  }
  for (let i = 5; i >= 1; i -= 1) {
    msg.textContent = `Raise the straight arm forward, toward the camera, not out to the side. Starting in ${i}`;
    await sleep(1000);
  }
  msg.textContent = 'Raise the straight arm slowly forward, toward the camera…';
  let raise;
  try {
    raise = await fetch('/api/straps/calibrate/raise', { method: 'POST' }).then((r) => r.json());
  } catch {
    raise = { ok: false, reason: 'Could not reach the station' };
  }
  buttons.forEach((b) => { b.disabled = false; });
  msg.textContent = raise.ok ? 'N-pose ok, raise ok' : (raise.reason || 'Raise was not accepted');
}

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
  const err = $('#rec-error');
  if (!r.ok) {
    err.hidden = false;
    err.textContent = r.reason || 'Recording not started';
    log('system', `Recording not started: ${r.reason}`);
    if (r.enabled === false) renderRecorder(r);
    return;
  }
  err.hidden = true;
  renderRecorder(r);
});
for (const action of ['prev', 'next', 'stop']) {
  $(`#rec-${action}`).addEventListener('click', async () => {
    const r = await api(`/api/record/${action}`, {});
    if (!r.ok) { log('system', r.reason || 'Recording step failed'); return; }
    renderRecorder(r);
  });
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

$('#straps-npose').addEventListener('click', () => strapCalibrate('/api/straps/calibrate/npose', 'Wear the sensors as they sit. Stand still, arms by your sides…'));
$('#straps-raise').addEventListener('click', () => strapCalibrate('/api/straps/calibrate/raise', 'Raise the straight arm forward, toward the camera. Not out to the side…'));
$('#straps-guided').addEventListener('click', () => guidedStraps());

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

function showPainCard() {
  $('#pain-stop-line').hidden = true;
  document.querySelectorAll('[data-pain]').forEach((b) => b.classList.remove('on'));
  $('#pain-card').hidden = false;
}

function submitPain(value) {
  const stopped = value >= PAIN_STOP;
  session.checkins.push({ value, at: new Date(), stopped });
  document.querySelectorAll('[data-pain]').forEach((b) => b.classList.toggle('on', Number(b.dataset.pain) === value));
  if (stopped) {
    $('#pain-stop-line').hidden = false;
    agent.paused = true;
    awaitingCheckin = false;
    setPaused(true);
    agent.say(PAIN_STOP_LINE, { priority: 3, kind: 'warn' });
    if (!agent.voiceOn && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(PAIN_STOP_LINE);
      u.lang = 'en-IN';
      window.speechSynthesis.speak(u);
    }
    return;
  }
  $('#pain-stop-line').hidden = true;
  if (awaitingCheckin) {
    awaitingCheckin = false;
    agent.paused = false;
    setPaused(false);
  }
  $('#pain-card').hidden = true;
}

document.querySelectorAll('[data-pain]').forEach((b) => b.addEventListener('click', () => submitPain(Number(b.dataset.pain))));
$('#pain-btn').addEventListener('click', showPainCard);
$('#end-btn').addEventListener('click', () => {
  fillSummary();
  $('#summary-card').hidden = false;
});
$('#summary-close').addEventListener('click', () => { $('#summary-card').hidden = true; });
$('#summary-new').addEventListener('click', () => {
  resetPageSession();
  $('#summary-card').hidden = true;
  showPainCard();
  setPaused(true);
});

api('/api/exercises').then((list) => { for (const e of list) ui.exercises[e.id] = e; }).catch(() => {});
api('/api/record/status').then(renderRecorder).catch(() => {});
api('/api/status').then((s) => {
  ui.side = s.side || 'right';
  document.querySelectorAll('[data-side]').forEach((x) => x.classList.toggle('on', x.dataset.side === ui.side));
  $('#model-name').textContent = `${s.pose_model || 'pose'} + depth`;
  if (s.camera_preview) {
    const btn = $('#video-btn');
    btn.hidden = false;
    vision.startPreview();
    btn.textContent = 'Hide camera';
    btn.addEventListener('click', () => {
      if (vision.live) {
        vision.stopPreview();
        btn.textContent = 'Show camera';
      } else {
        vision.startPreview();
        btn.textContent = 'Hide camera';
      }
    });
  }
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
