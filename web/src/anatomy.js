import * as THREE from 'three';
import { Avatar } from './avatar.js';
import { boneMaterial, capsuleMaterial, muscleMaterial } from './anatomyMaterials.js';
import { fadeMaterial } from './tween.js';

// Real anatomy (Z-Anatomy / BodyParts3D, CC BY-SA 4.0) rigged by tools/blender/build_anatomy.py and
// driven by the same camera skeleton as the clothed avatar, scaled to the avatar's shoulders.
// Layers fade like the CodePen viewer; tissues light up from the live measurements:
//   * glenohumeral capsule region being stretched (the tissue that tightens in frozen shoulder)
//   * prime-mover muscles of the current movement ("working")
//   * upper trapezius / levator scapulae when the hub flags a SHRUG
export const ANATOMY_URL = '/models/anatomy_upper.glb';
export const ATTRIBUTION = 'Anatomy: Z-Anatomy (CC BY-SA 4.0), BodyParts3D © DBCLS (CC BY-SA 2.1 JP)';

// Teaching model: main movers per movement (simplified).
const MOVERS = {
  flexion: ['Clavicular_part_of_deltoid_muscle', 'Clavicular_head_of_pectoralis_major_muscle', 'Long_head_of_biceps_brachii', 'Coracobrachialis_muscle'],
  scaption: ['Acromial_part_of_deltoid_muscle', 'Clavicular_part_of_deltoid_muscle', 'Supraspinatus_muscle'],
  abduction: ['Acromial_part_of_deltoid_muscle', 'Supraspinatus_muscle'],
  extension: ['Scapular_spinal_part_of_deltoid_muscle', 'Latissimus_dorsi_muscle', 'Teres_major_muscle', 'Long_head_of_triceps_brachii'],
  er: ['Infraspinatus_muscle', 'Teres_minor_muscle', 'Scapular_spinal_part_of_deltoid_muscle'],
  ir: ['Subscapularis_muscle', 'Sternocostal_head_of_pectoralis_major_muscle', 'Latissimus_dorsi_muscle', 'Teres_major_muscle'],
  shrug: ['Descending_part_of_trapezius_muscle', 'Levator_scapulae'],
};

const pretty = (id) => id.replace(/_/g, ' ').replace(/ muscle$/, '').replace(/^(\w)/, (c) => c.toUpperCase());

export class RealAnatomy {
  static async load(shoulderWidth, onProgress) {
    const rig = await Avatar.load(ANATOMY_URL, { shoulderWidth, onProgress });
    return new RealAnatomy(rig);
  }

  constructor(rig) {
    this.rig = rig;
    this.muscles = [];   // { mesh, id, side, mat }
    this.capsules = [];  // { mesh, side, mat }
    this.layers = { skin: 1, muscles: 0, bones: 0, joints: 0 };
    this.mats = { bone: boneMaterial(), ligament: capsuleMaterial(null, false) };
    rig.root.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = false;
      o.frustumCulled = false;
      const m = /^PB_(M|J)__(.+)__(L|R)$/.exec(o.name);
      if (o.name.startsWith('PB_SKELETON')) {
        o.material = this.mats.bone;
      } else if (m && m[1] === 'M') {
        if (/bursa/i.test(m[2])) {
          o.material = capsuleMaterial(null, false);
          this.capsules.push({ mesh: o, side: m[3] === 'R' ? 'right' : 'left', mat: o.material, bursa: true });
        } else {
          const mat = muscleMaterial(o.geometry);
          o.material = mat;
          this.muscles.push({ mesh: o, id: m[2], side: m[3] === 'R' ? 'right' : 'left', mat });
        }
      } else if (m && m[1] === 'J') {
        const gh = m[2] === 'Articular_capsule_of_glenohumeral_joint';
        o.material = gh ? capsuleMaterial(o.geometry, true) : this.mats.ligament;
        if (gh) this.capsules.push({ mesh: o, side: m[3] === 'R' ? 'right' : 'left', mat: o.material, gh: true });
        o.renderOrder = 3;
      }
    });
    rig.skinMaterials.clear();
  }

  get root() { return this.rig.root; }

  solve(kp) { this.rig.solve(kp); }

  step(dt) { this.rig.step(dt); }

  // Measurements -> highlights. Returns a human-readable explanation for the AI panel.
  update(angles, flags, side, t) {
    const stretch = new THREE.Vector4(); // superior, inferior, anterior, posterior
    let moverKey = null;
    if (angles) {
      const e = angles.elevation?.value;
      const r = angles.rotation?.value;
      if (e != null) stretch.y = THREE.MathUtils.clamp((e - 30) / 110, 0, 1);
      if (r != null && r > 0) stretch.z = THREE.MathUtils.clamp(r / 60, 0, 1);
      if (r != null && r < 0) stretch.w = THREE.MathUtils.clamp(-r / 50, 0, 1);
      if (r != null && Math.abs(r) > 8) moverKey = r > 0 ? 'er' : 'ir';
      else if (e != null && e > 20 && MOVERS[angles.movement]) moverKey = angles.movement;
    }
    const shrug = flags?.includes('SHRUG');
    const working = new Set([...(MOVERS[moverKey] || []), ...(shrug ? MOVERS.shrug : [])]);
    for (const m of this.muscles) {
      const target = m.side === side && working.has(m.id) ? 1 : 0;
      const u = m.mat.userData.uniforms;
      u.uActive.value += (target - u.uActive.value) * 0.15;
      u.uTime.value = t;
    }
    for (const c of this.capsules) {
      if (!c.gh) continue;
      const u = c.mat.userData.uniforms;
      u.uStretch.value.lerp(c.side === side ? stretch : new THREE.Vector4(), 0.2);
      u.uTime.value = t;
    }
    const regions = ['superior', 'inferior (axillary pouch)', 'anterior', 'posterior'];
    const arr = stretch.toArray();
    const top = arr.indexOf(Math.max(...arr));
    return {
      working: [...working].map(pretty),
      stretching: arr[top] > 0.1 ? `${regions[top]} glenohumeral capsule` : null,
      stretchAmount: arr[top],
    };
  }

  setLayers(next, ms = 700) {
    Object.assign(this.layers, next);
    fadeMaterial(this.mats.bone, this.layers.bones, ms);
    for (const m of this.muscles) fadeMaterial(m.mat, this.layers.muscles, ms);
    fadeMaterial(this.mats.ligament, this.layers.joints * 0.85, ms);
    for (const c of this.capsules) fadeMaterial(c.mat, this.layers.joints * (c.bursa ? 0.45 : 0.85), ms);
    const show = this.layers.bones + this.layers.muscles + this.layers.joints > 0.01;
    clearTimeout(this._hideTimer);
    if (show) this.root.visible = true;
    else this._hideTimer = setTimeout(() => { this.root.visible = false; }, ms); // skip skinning cost when hidden
  }
}

export const LAYER_PRESETS = {
  avatar: { skin: 1, muscles: 0, bones: 0, joints: 0 },
  xray: { skin: 0.14, muscles: 1, bones: 1, joints: 1 },
  anatomy: { skin: 0, muscles: 1, bones: 1, joints: 1 },
};
