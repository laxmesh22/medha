import * as THREE from 'three';
import { Avatar } from './avatar.js';
import { Stage } from './stage.js';

// Full-screen guided calibration: large text, a countdown, and two figures side by side.
// "Do this" acts out the step; "You" follows the worn bands live, so the patient can match it.
// Display only: the calibration itself is measured on the station (straps/calibrate.py).

const SPREAD = 0.62;              // half the distance between the two figures (m)
const STILL_DPS = 15;             // band turning speed above which the stand-still step will be rejected

const STEPS = {
  npose: { title: 'Stand still', text: 'Arms hanging straight at your sides, palms facing your thighs. Do not move.' },
  raise: { title: 'Forward raise', text: 'Keep your elbow straight. Raise your arm slowly forward, toward the screen, up past your shoulder.' },
  side: { title: 'Side raise', text: 'Arm back down. Keep your elbow straight and raise your arm slowly out to the side, up to shoulder level.' },
  lean: { title: 'Lean forward', text: 'Arms relaxed. Bend slowly forward from the hips toward the screen, then come back up.' },
};

// Demo directions in the strap display frame: x patient's left, y up, z toward the camera.
function demoPose(step, side, t) {
  const swing = (Math.sin(t * 1.4 - Math.PI / 2) + 1) / 2;          // 0..1..0, slow
  const down = [0, -1, 0];
  if (step === 'raise') {
    const a = swing * THREE.MathUtils.degToRad(110);
    const v = [0, -Math.cos(a), Math.sin(a)];
    return { side, upper_arm: v, forearm: v };
  }
  if (step === 'side') {
    const a = swing * THREE.MathUtils.degToRad(90);
    const out = side === 'left' ? 1 : -1;
    const v = [out * Math.sin(a), -Math.cos(a), 0];
    return { side, upper_arm: v, forearm: v };
  }
  if (step === 'lean') {
    const a = swing * THREE.MathUtils.degToRad(25);
    return { side, trunk: [0, Math.cos(a), Math.sin(a)], upper_arm: down, forearm: down };
  }
  return { side, upper_arm: down, forearm: down };
}

export class CalibrationOverlay {
  constructor({ modelUrl, displayPose }) {
    this.modelUrl = modelUrl;         // () => url of the figure the station shows
    this.displayPose = displayPose;   // (strap_pose) => pose for the figure, mirrored like the main view
    this.el = document.getElementById('calib');
    this.step = null;
    this.t = 0;
    this.ready = null;
    this.el.querySelector('#calib-close').addEventListener('click', () => this.close());
  }

  async open() {
    this.el.hidden = false;
    document.body.classList.add('calib-open');
    if (!this.ready) this.ready = this.build();
    else this.stage.start();
    await this.ready;
  }

  close() {
    this.el.hidden = true;
    document.body.classList.remove('calib-open');
    this.stage?.stop();
    this.onClose?.();
  }

  async build() {
    this.stage = new Stage(this.el.querySelector('#calib-scene'));
    this.stage.camera.position.set(0, -0.15, 4.4);
    this.stage.controls.target.set(0, -0.35, 0);
    const url = this.modelUrl();
    const [demo, you] = await Promise.all([Avatar.load(url), Avatar.load(url)]);
    demo.root.position.x -= SPREAD;
    you.root.position.x += SPREAD;
    // Tint the demo figure so the two read apart at a glance.
    for (const m of demo.skinMaterials) { m.transparent = true; m.opacity = 0.55; }
    this.stage.scene.add(demo.root, you.root);
    this.stage.setFloorY(Math.min(demo.footY, you.footY));
    this.demo = demo;
    this.you = you;
    this.stage.onFrame.push((dt) => {
      this.t += dt;
      // Mirrored exactly like "You", so both figures raise the same arm on screen.
      if (this.step) demo.solveStrap(this.displayPose(demoPose(this.step, this.side, this.t)));
      demo.step(dt);
      you.step(dt);
    });
  }

  // Each step: title, instruction, then a countdown (seconds) before the station starts measuring.
  async show(step, side, countdown) {
    this.step = step;
    this.side = side;
    this.t = 0;
    const s = STEPS[step];
    const order = Object.keys(STEPS);
    this.el.querySelector('#calib-step').textContent = `Step ${order.indexOf(step) + 1} of ${order.length}`;
    this.el.querySelector('#calib-title').textContent = s.title;
    this.el.querySelector('#calib-text').textContent = s.text;
    this.setResult(null);
    for (let i = countdown; i >= 1; i -= 1) {
      this.el.querySelector('#calib-count').textContent = String(i);
      await new Promise((r) => setTimeout(r, 1000));
      if (this.el.hidden) return false;
    }
    this.el.querySelector('#calib-count').textContent = 'Now';
    return true;
  }

  // ok: true (green), false (red, with a reason), null (clear).
  setResult(ok, text = '') {
    const r = this.el.querySelector('#calib-result');
    r.hidden = ok === null;
    r.dataset.ok = ok ? 'yes' : 'no';
    r.textContent = text;
    this.el.querySelector('#calib-actions').hidden = ok !== false;
  }

  finish(text) {
    this.step = 'npose';
    this.el.querySelector('#calib-step').textContent = 'Done';
    this.el.querySelector('#calib-title').textContent = 'Calibration complete';
    this.el.querySelector('#calib-text').textContent = 'The figure now follows your bands. Close this to start exercising.';
    this.el.querySelector('#calib-count').textContent = '✓';
    this.setResult(true, text);
  }

  // Live: the "You" figure and a hold-still warning while measuring the stand-still step.
  update(state) {
    if (this.el.hidden || !this.you) return;
    const pose = state.strap_pose;
    if (pose && (pose.trunk || pose.upper_arm || pose.forearm)) this.you.solveStrap(this.displayPose(pose));
    const speed = Math.max(0, ...((state.straps?.devices || []).map((d) => d.gyro_dps || 0)));
    const warn = this.el.querySelector('#calib-still');
    warn.hidden = !(this.step === 'npose' && this.el.querySelector('#calib-count').textContent === 'Now' && speed > STILL_DPS);
  }
}
