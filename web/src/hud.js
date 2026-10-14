// Live displays fed by the hub: camera-model overlay, phase tracker, angle chart, rep history.
// Everything shown is derived from the hub's measurements; missing data stays missing (never 0).

const BONES = [[5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4]];
const ARM = { right: [6, 8, 10], left: [5, 7, 9] };
const ARM_LABEL = ['Shoulder', 'Elbow', 'Wrist'];
export const PALETTE = {
  accent: '#4fc6a6', warn: '#e3a24a', danger: '#e06c64', t1: '#e8edf3', t2: '#a3afbf', t3: '#6b7686', line: 'rgba(160,178,200,0.10)',
};
const MONO = '"Geist Mono Variable", ui-monospace, Consolas, monospace';
const SANS = '"Geist Variable", system-ui, sans-serif';

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
    this.t0 = performance.now();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    const loop = () => { this.draw(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }

  resize() {
    this.w = this.c.parentElement.clientWidth;
    this.h = Math.round(this.w / (this.state?.image_aspect || 16 / 9));
    this.ctx = fitCanvas(this.c, this.w, this.h);
  }

  update(state) {
    const changed = state.image_aspect && state.image_aspect !== this.state?.image_aspect;
    this.state = state;
    if (changed) this.resize();
  }

  draw() {
    const { ctx, w, h } = this;
    const s = this.state;
    const t = (performance.now() - this.t0) / 1000;
    const videoOn = this.img && !this.img.hidden && this.img.naturalWidth > 0;
    ctx.clearRect(0, 0, w, h);
    if (!videoOn) { // privacy mode: dotted field instead of video
      ctx.fillStyle = 'rgba(160,178,200,0.10)';
      for (let x = 10; x < w; x += 18) for (let y = 10; y < h; y += 18) ctx.fillRect(x, y, 1.2, 1.2);
    }
    const sy = ((t * 0.3) % 1) * h; // sweep
    const g = ctx.createLinearGradient(0, sy - 40, 0, sy);
    g.addColorStop(0, 'rgba(79,198,166,0)'); g.addColorStop(1, 'rgba(79,198,166,0.10)');
    ctx.fillStyle = g; ctx.fillRect(0, sy - 40, w, 40);

    const kp = s?.kp2d, sc = s?.scores;
    if (!kp) {
      this.text(w / 2, h / 2, 'Looking for a person', PALETTE.t3, 14, 'center', SANS);
      return;
    }
    const P = (i) => [kp[i][0] * w, kp[i][1] * h];
    const ok = (i) => sc && sc[i] >= 0.4;
    ctx.lineWidth = 2; ctx.lineCap = 'round';
    ctx.strokeStyle = 'rgba(232,237,243,0.55)';
    for (const [a, b] of BONES) {
      if (!ok(a) || !ok(b)) continue;
      ctx.beginPath(); ctx.moveTo(...P(a)); ctx.lineTo(...P(b)); ctx.stroke();
    }
    for (let i = 0; i < kp.length; i++) {
      if (!sc || sc[i] < 0.2) continue;
      const [x, y] = P(i);
      ctx.fillStyle = sc[i] >= 0.7 ? PALETTE.accent : sc[i] >= 0.4 ? PALETTE.warn : PALETTE.danger;
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();
    }
    const pts = kp.filter((_, i) => ok(i)).map((p) => [p[0] * w, p[1] * h]);
    if (pts.length > 3) { // corner brackets around the tracked person
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      const x0 = Math.min(...xs) - 16, x1 = Math.max(...xs) + 16, y0 = Math.min(...ys) - 22, y1 = Math.max(...ys) + 16;
      ctx.strokeStyle = PALETTE.accent; ctx.lineWidth = 1.5;
      for (const [cx, cy, dx, dy] of [[x0, y0, 1, 1], [x1, y0, -1, 1], [x0, y1, 1, -1], [x1, y1, -1, -1]]) {
        ctx.beginPath(); ctx.moveTo(cx, cy + dy * 12); ctx.lineTo(cx, cy); ctx.lineTo(cx + dx * 12, cy); ctx.stroke();
      }
      const conf = sc.reduce((a, b) => a + Math.min(b, 1), 0) / sc.length;
      this.text(x0, y0 - 7, `patient  ${(conf * 100).toFixed(0)}%`, PALETTE.accent, 11, 'left', MONO);
    }
    const arm = ARM[s.side] || ARM.right;
    arm.forEach((i, k) => {
      if (!ok(i)) return;
      const [x, y] = P(i);
      ctx.strokeStyle = 'rgba(232,237,243,0.7)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(x, y, 9 + 1.5 * Math.sin(t * 4 + k), 0, Math.PI * 2); ctx.stroke();
      this.text(x + 13, y + 4, `${ARM_LABEL[k]} ${(Math.min(sc[i], 1) * 100).toFixed(0)}%`, PALETTE.t2, 10.5, 'left', MONO);
    });
    const e = s.angles?.elevation;
    if (ok(arm[0]) && ok(arm[1]) && ok(11) && ok(12)) {
      const [sx, sy2] = P(arm[0]), [ex, ey] = P(arm[1]);
      const hip = [(P(11)[0] + P(12)[0]) / 2, (P(11)[1] + P(12)[1]) / 2];
      const sh = [(P(5)[0] + P(6)[0]) / 2, (P(5)[1] + P(6)[1]) / 2];
      const down = Math.atan2(hip[1] - sh[1], hip[0] - sh[0]);
      let d = Math.atan2(ey - sy2, ex - sx) - down;
      while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI;
      ctx.strokeStyle = e?.value != null ? PALETTE.accent : PALETTE.t3; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(sx, sy2, 32, down, down + d, d < 0); ctx.stroke();
      this.text(sx + (d > 0 ? -76 : 40), sy2 - 36, e?.value != null ? `${Math.round(e.value)}°` : 'n/a', PALETTE.t1, 17, 'left', SANS, true);
    }
    this.text(10, h - 10, `${s.fps} fps  ${s.proc_ms} ms  ${videoOn ? 'live video' : 'privacy mode: keypoints only'}`, PALETTE.t3, 10.5, 'left', MONO);
  }

  text(x, y, str, color, size, align, family, box = false) {
    const { ctx } = this;
    ctx.font = `600 ${size}px ${family}`;
    ctx.textAlign = align;
    if (box) {
      const m = ctx.measureText(str);
      ctx.fillStyle = 'rgba(11,15,20,0.8)';
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
