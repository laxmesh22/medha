// Live displays fed by the hub: camera-model overlay, phase tracker, angle chart, rep history.
// Everything shown is derived from the hub's measurements; missing data stays missing (never 0).

const BONES = [[5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4]];
const ARM = { right: [6, 8, 10], left: [5, 7, 9] };
const ARM_LABEL = ['Shoulder', 'Elbow', 'Wrist'];
export const PALETTE = {
  accent: '#0a4a4f', warn: '#8a5a00', danger: '#a42828', t1: '#10201f', t2: '#4a5857', t3: '#4a5857',
  line: 'rgba(16,32,31,0.10)', on: '#f5f2ea', soft: '#dcebe8', warning: '#fab219', serious: '#ec835a',
};
const MONO = 'ui-monospace, "Cascadia Mono", Consolas, monospace';
const SANS = 'system-ui, "Segoe UI", Roboto, sans-serif';

function fitCanvas(c, w, h) {
  const dpr = Math.min(window.devicePixelRatio, 2);
  c.width = w * dpr; c.height = h * dpr; c.style.height = `${h}px`;
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

// ------------------------------------------------------------------------------------------- vision
export class VisionPanel {
  constructor(canvas, img) {
    this.c = canvas;
    this.img = img;
    this.state = null;
    this.byFrame = new Map();
    this.preview = null;
    this.live = true;
    this.t0 = performance.now();
    this.paints = 0;
    this.matches = 0;
    this.closed = 0;
    this.delays = [];
    this.firstPaint = null;
    this.lastPaint = null;
    this.lastPainted = null;
    this.lastMatched = false;
    window.__auriVision = this;
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    const loop = () => {
      try { this.draw(); }
      catch (err) { this.error = String(err && err.stack ? err.stack : err); }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  resize() {
    this.w = this.c.parentElement.clientWidth;
    const bmp = this.preview?.bmp;
    const aspect = bmp ? bmp.width / bmp.height : (this.state?.image_aspect || 4 / 3);
    this.h = Math.round(this.w / aspect);
    this.ctx = fitCanvas(this.c, this.w, this.h);
  }

  resetStats() {
    this.paints = 0;
    this.fetched = 0;
    this.matches = 0;
    this.closed = 0;
    this.delays = [];
    this.firstPaint = null;
    this.lastPaint = null;
    this.lastPainted = null;
    this.lastMatched = false;
  }

  update(state, preview) {
    this.state = state;
    if (state?.frame != null) {
      this.byFrame.set(state.frame, state);
      for (const key of this.byFrame.keys()) {
        if (key < state.frame - 12) this.byFrame.delete(key);
      }
    }
    const bmp = this.preview?.bmp;
    const aspect = bmp ? bmp.width / bmp.height : state?.image_aspect;
    if (aspect && this.h && Math.abs(aspect - this.w / this.h) > 0.02) this.resize();
  }

  startPreview() {
    this.live = true;
    if (!this._worker) {
      // Fetch and JPEG decode stay off the UI thread. Only the newest bitmap is posted,
      // so a slow paint cannot build a queue of old frames.
      const source = [
        'let after = -1, live = false, posted = false, pending = null, started = false;',
        'function flush() {',
        '  if (!pending || posted) return;',
        '  posted = true; const shot = pending; pending = null;',
        '  self.postMessage(shot, [shot.bmp]);',
        '}',
        'self.onmessage = (ev) => {',
        '  if (ev.data === "stop") { live = false; return; }',
        '  if (ev.data === "ack") { posted = false; flush(); return; }',
        '  if (ev.data === "start") { live = true; if (!started) { started = true; pump(); } }',
        '};',
        'async function pump() {',
        '  while (true) {',
        '    if (!live) { await new Promise((r) => setTimeout(r, 50)); continue; }',
        '    let res;',
        '    try { res = await fetch("/api/camera/preview.jpg?after=" + after, { cache: "no-store" }); }',
        '    catch (err) { await new Promise((r) => setTimeout(r, 200)); continue; }',
        '    if (!live || res.status === 204) continue;',
        '    const frame = Number(res.headers.get("X-Auri-Frame"));',
        '    const tMs = Number(res.headers.get("X-Auri-Time"));',
        '    if (!Number.isFinite(frame) || frame <= after) continue;',
        '    let bmp;',
        '    try { bmp = await createImageBitmap(await res.blob()); }',
        '    catch (err) { continue; }',
        '    after = frame;',
        '    if (pending) pending.bmp.close();',
        '    pending = { frame: frame, t_ms: Number.isFinite(tMs) ? tMs : null, bmp: bmp };',
        '    flush();',
        '  }',
        '}',
      ].join('\n');
      this._worker = new Worker(URL.createObjectURL(new Blob([source], { type: 'text/javascript' })));
      this._worker.onmessage = (ev) => {
        const shot = ev.data;
        if (!this.live || (this.preview && shot.frame < this.preview.frame)) {
          shot.bmp.close();
          this._worker.postMessage('ack');
          return;
        }
        if (this.preview?.bmp) this.preview.bmp.close();
        this.preview = shot;
        this.fetched = (this.fetched || 0) + 1;
        const aspect = shot.bmp.width / shot.bmp.height;
        if (this.h && Math.abs(aspect - this.w / this.h) > 0.02) this.resize();
        try { this.draw(); }
        catch (err) { this.error = String(err && err.stack ? err.stack : err); }
        this._worker.postMessage('ack');
      };
    }
    this._worker.postMessage('start');
  }

  stopPreview() {
    this.live = false;
    if (this._worker) this._worker.postMessage('stop');
  }

  draw() {
    const { ctx, w, h } = this;
    const t = (performance.now() - this.t0) / 1000;
    const show = this.live && this.preview?.bmp;
    ctx.clearRect(0, 0, w, h);
    let s = null;
    let mirror = false;
    if (!show) {
      ctx.fillStyle = 'rgba(245,242,234,0.35)';
      for (let x = 10; x < w; x += 18) for (let y = 10; y < h; y += 18) ctx.fillRect(x, y, 1.2, 1.2);
      const sy = ((t * 0.3) % 1) * h;
      const g = ctx.createLinearGradient(0, sy - 40, 0, sy);
      g.addColorStop(0, 'rgba(245,242,234,0)'); g.addColorStop(1, 'rgba(245,242,234,0.14)');
      ctx.fillStyle = g; ctx.fillRect(0, sy - 40, w, 40);
      s = this.state;
    } else {
      const shot = this.preview;
      mirror = document.getElementById('mirror')?.checked !== false;
      ctx.drawImage(shot.bmp, mirror ? w : 0, 0, mirror ? -w : w, h);
      if (shot.frame !== this.lastPainted) {
        if (this.lastPainted != null) {
          this.closed += 1;
          if (this.lastMatched) this.matches += 1;
        }
        this.lastPainted = shot.frame;
        this.lastMatched = this.byFrame.has(shot.frame);
        this.paints += 1;
        const now = performance.now();
        if (this.firstPaint == null) this.firstPaint = now;
        this.lastPaint = now;
        if (Number.isFinite(shot.t_ms)) {
          this.delays.push(Date.now() - shot.t_ms);
          if (this.delays.length > 4000) this.delays.splice(0, this.delays.length - 4000);
        }
      } else if (this.byFrame.has(shot.frame)) {
        this.lastMatched = true;
      }
      // Skeleton only from this JPEG's frame. A newer pose is not drawn on an older image.
      s = this.byFrame.get(shot.frame) || null;
    }

    const kp = s?.kp2d, sc = s?.scores;
    if (!kp) {
      if (!show) this.text(w / 2, h / 2, 'Looking for a person', PALETTE.on, 14, 'center', SANS);
      else this.text(10, h - 10, this._foot(show), PALETTE.soft, 10.5, 'left', MONO);
      return;
    }
    const P = (i) => {
      const u = mirror ? 1 - kp[i][0] : kp[i][0];
      return [u * w, kp[i][1] * h];
    };
    const ok = (i) => sc && sc[i] >= 0.4;
    ctx.lineCap = 'round';
    for (const [a, b] of BONES) {
      if (!ok(a) || !ok(b)) continue;
      ctx.beginPath(); ctx.moveTo(...P(a)); ctx.lineTo(...P(b));
      ctx.strokeStyle = '#063a3e'; ctx.lineWidth = 4; ctx.stroke();
      ctx.strokeStyle = PALETTE.on; ctx.lineWidth = 2; ctx.stroke();
    }
    for (let i = 0; i < kp.length; i++) {
      if (!sc || sc[i] < 0.2) continue;
      const [x, y] = P(i);
      ctx.fillStyle = sc[i] >= 0.7 ? PALETTE.on : sc[i] >= 0.4 ? PALETTE.warning : PALETTE.serious;
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();
    }
    const pts = kp.map((_, i) => (ok(i) ? P(i) : null)).filter(Boolean);
    if (pts.length > 3) { // corner brackets around the tracked person
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      const x0 = Math.min(...xs) - 16, x1 = Math.max(...xs) + 16, y0 = Math.min(...ys) - 22, y1 = Math.max(...ys) + 16;
      ctx.strokeStyle = PALETTE.on; ctx.lineWidth = 1.5;
      for (const [cx, cy, dx, dy] of [[x0, y0, 1, 1], [x1, y0, -1, 1], [x0, y1, 1, -1], [x1, y1, -1, -1]]) {
        ctx.beginPath(); ctx.moveTo(cx, cy + dy * 12); ctx.lineTo(cx, cy); ctx.lineTo(cx + dx * 12, cy); ctx.stroke();
      }
      const conf = sc.reduce((a, b) => a + Math.min(b, 1), 0) / sc.length;
      this.text(x0, y0 - 7, `patient  ${(conf * 100).toFixed(0)}%`, PALETTE.on, 11, 'left', MONO);
    }
    const arm = ARM[s.side] || ARM.right;
    arm.forEach((i, k) => {
      if (!ok(i)) return;
      const [x, y] = P(i);
      ctx.strokeStyle = 'rgba(245,242,234,0.85)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(x, y, 9 + 1.5 * Math.sin(t * 4 + k), 0, Math.PI * 2); ctx.stroke();
      this.text(x + 13, y + 4, `${ARM_LABEL[k]} ${(Math.min(sc[i], 1) * 100).toFixed(0)}%`, PALETTE.on, 10.5, 'left', MONO);
    });
    const e = s.angles?.elevation;
    if (ok(arm[0]) && ok(arm[1]) && ok(11) && ok(12)) {
      const [sx, sy2] = P(arm[0]), [ex, ey] = P(arm[1]);
      const hip = [(P(11)[0] + P(12)[0]) / 2, (P(11)[1] + P(12)[1]) / 2];
      const sh = [(P(5)[0] + P(6)[0]) / 2, (P(5)[1] + P(6)[1]) / 2];
      const down = Math.atan2(hip[1] - sh[1], hip[0] - sh[0]);
      let d = Math.atan2(ey - sy2, ex - sx) - down;
      while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI;
      ctx.strokeStyle = e?.value != null ? PALETTE.on : PALETTE.soft; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(sx, sy2, 32, down, down + d, d < 0); ctx.stroke();
      this.text(sx + (d > 0 ? -76 : 40), sy2 - 36, e?.value != null ? `${Math.round(e.value)}°` : 'n/a', PALETTE.on, 17, 'left', SANS, true);
    }
    this.text(10, h - 10, this._foot(show), PALETTE.soft, 10.5, 'left', MONO);
  }

  _foot(show) {
    const s = this.state;
    const fps = s?.fps ?? '';
    const ms = s?.proc_ms ?? '';
    return `${fps} fps  ${ms} ms  ${show ? 'live video' : 'privacy mode: keypoints only'}`;
  }

  text(x, y, str, color, size, align, family, box = false) {
    const { ctx } = this;
    ctx.font = `600 ${size}px ${family}`;
    ctx.textAlign = align;
    if (box) {
      const m = ctx.measureText(str);
      ctx.fillStyle = '#063a3e';
      ctx.beginPath(); ctx.roundRect(x - 6, y - size - 2, m.width + 12, size + 9, 6); ctx.fill();
    }
    ctx.fillStyle = color;
    ctx.fillText(str, x, y);
    ctx.textAlign = 'left';
  }
}

// ------------------------------------------------------------------------------------------- phase / reps
export function renderPhase(el, coach) {
  const order = ['rest', 'raising', 'hold', 'lowering'];
  el.querySelectorAll('[data-phase]').forEach((s) => {
    s.classList.toggle('active', s.dataset.phase === coach?.state);
    s.classList.toggle('done', !!coach && order.indexOf(s.dataset.phase) < order.indexOf(coach.state));
  });
  el.dataset.paused = coach?.state === 'paused' ? 'yes' : 'no';
}

export function renderReps(el, coach) {
  const reps = coach?.reps || [];
  const key = reps.map((r) => r.n).join(',');
  if (el.dataset.key === key) return;
  el.dataset.key = key;
  el.innerHTML = '';
  if (!reps.length) {
    el.innerHTML = '<li class="empty">Completed reps appear here, marked correct or needs fixing.</li>';
    return;
  }
  for (const r of reps) {
    const li = document.createElement('li');
    li.className = r.correct ? '' : 'bad';
    li.title = r.correct ? 'Correct' : `Needs fixing: ${r.issues.join(', ')}`;
    li.innerHTML = `${r.correct ? '✓' : '✕'} ${Math.round(r.peak)}° <small>#${r.n}</small>`;
    el.appendChild(li);
  }
}

// ------------------------------------------------------------------------------------------- chart
export class AngleChart {
  constructor(canvas, seconds = 16) {
    this.c = canvas;
    this.seconds = seconds;
    this.buf = [];
    this.peaks = [];
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
  }

  resize() {
    this.w = this.c.parentElement.clientWidth - 36; this.h = 150;
    this.ctx = fitCanvas(this.c, this.w, this.h);
  }

  push(coach) {
    const now = performance.now() / 1000;
    this.buf.push([now, coach?.value ?? null]);
    while (this.buf.length && this.buf[0][0] < now - this.seconds) this.buf.shift();
    const n = coach?.rep_count || 0;
    if (n > (this.lastReps || 0) && coach.reps.length) {
      const r = coach.reps[coach.reps.length - 1];
      this.peaks.push([now, r.peak, r.correct]);
    }
    this.lastReps = n;
    this.peaks = this.peaks.filter((p) => p[0] > now - this.seconds);
    this.draw(now, coach?.target ?? 120);
  }

  draw(now, target) {
    const { ctx, w, h } = this;
    const max = Math.max(180, target + 10);
    const X = (t) => w - ((now - t) / this.seconds) * w;
    const Y = (v) => h - 10 - (v / max) * (h - 22);
    ctx.clearRect(0, 0, w, h);
    ctx.font = `500 10.5px ${MONO}`;
    for (const v of [0, 45, 90, 135, 180]) {
      ctx.strokeStyle = PALETTE.line; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(30, Y(v)); ctx.lineTo(w, Y(v)); ctx.stroke();
      ctx.fillStyle = PALETTE.t3; ctx.fillText(`${v}°`, 0, Y(v) + 3);
    }
    ctx.setLineDash([5, 5]); ctx.strokeStyle = PALETTE.t2;
    ctx.beginPath(); ctx.moveTo(30, Y(target)); ctx.lineTo(w, Y(target)); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = PALETTE.t2; ctx.fillText(`target ${target}°`, w - 80, Y(target) - 6);
    // area + line; gaps stay gaps (missing data is never drawn as 0)
    ctx.strokeStyle = PALETTE.accent; ctx.lineWidth = 2.2; ctx.lineJoin = 'round';
    ctx.beginPath();
    let pen = false;
    for (const [t, v] of this.buf) {
      if (v == null || X(t) < 30) { pen = false; continue; }
      if (pen) ctx.lineTo(X(t), Y(v)); else { ctx.moveTo(X(t), Y(v)); pen = true; }
    }
    ctx.stroke();
    for (const [t, v, good] of this.peaks) {
      if (X(t) < 30) continue;
      ctx.fillStyle = good ? PALETTE.accent : PALETTE.warn;
      ctx.beginPath(); ctx.arc(X(t), Y(v), 4.5, 0, Math.PI * 2); ctx.fill();
      ctx.fillText(`${good ? '✓' : '✕'} ${Math.round(v)}°`, X(t) - 18, Y(v) - 10);
    }
  }
}
