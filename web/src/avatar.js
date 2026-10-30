import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// Rigged human driven by the camera skeleton. Mixamo and 3ds Max Biped rigs are supported.
// Retargeting = per-bone "swing": rotate each bone from its rest direction onto the measured segment
// direction (spine: hips->shoulders, arm: shoulder->elbow, forearm: elbow->wrist). Display only:
// the clinical numbers always come from the hub, never from the avatar.
//
// Licence: Rocketbox avatars are MIT (github.com/microsoft/Microsoft-Rocketbox). The Xbot mannequin
// ships with the three.js examples (Mixamo character): demo use only.
export const MODELS = {
  // Microsoft Rocketbox avatars (MIT licence), converted by tools/blender/rocketbox_to_glb.py
  female: { url: '/models/Sports_Female_02.glb', label: 'Female' },
  male: { url: '/models/Sports_Male_04.glb', label: 'Male' },
  mannequin: { url: '/models/Xbot.glb', label: 'Mannequin' },
};

// Bone name candidates: Mixamo ("mixamorigX" / "X") and 3ds Max Biped as used by Rocketbox.
// ... plus the PB_* rig of the real-anatomy model (tools/blender/build_anatomy.py).
const BONE_NAMES = {
  hips: ['mixamorigHips', 'Hips', 'Bip01_Pelvis', 'PB_Pelvis'],
  spine: ['mixamorigSpine', 'Spine', 'Bip01_Spine', 'PB_Thorax'],
  // Chest only. On this rig the thighs are children of the spine, so aiming that bone throws the legs.
  spine1: ['mixamorigSpine1', 'Spine1', 'Bip01_Spine1', 'PB_Chest'],
  neck: ['mixamorigNeck', 'Neck', 'Bip01_Neck', 'PB_Neck'],
  head: ['mixamorigHead', 'Head', 'Bip01_Head', 'PB_Head'],
  rShoulder: ['mixamorigRightShoulder', 'RightShoulder', 'Bip01_R_Clavicle', 'PB_Girdle_R'],
  rArm: ['mixamorigRightArm', 'RightArm', 'Bip01_R_UpperArm', 'PB_Humerus_R'],
  rFore: ['mixamorigRightForeArm', 'RightForeArm', 'Bip01_R_Forearm', 'PB_Forearm_R'],
  rHand: ['mixamorigRightHand', 'RightHand', 'Bip01_R_Hand', 'PB_Hand_R'],
  lShoulder: ['mixamorigLeftShoulder', 'LeftShoulder', 'Bip01_L_Clavicle', 'PB_Girdle_L'],
  lArm: ['mixamorigLeftArm', 'LeftArm', 'Bip01_L_UpperArm', 'PB_Humerus_L'],
  lFore: ['mixamorigLeftForeArm', 'LeftForeArm', 'Bip01_L_Forearm', 'PB_Forearm_L'],
  lHand: ['mixamorigLeftHand', 'LeftHand', 'Bip01_L_Hand', 'PB_Hand_L'],
};

const KP = { lSh: 5, rSh: 6, lEl: 7, rEl: 8, lWr: 9, rWr: 10, lHip: 11, rHip: 12 };
const MIRROR_PAIRS = [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11, 12], [13, 14], [15, 16]];
const V = (p) => new THREE.Vector3(p[0], p[1], p[2]);

// Mirror view: reflect x and swap left/right labels so the avatar behaves like a mirror image.
export function mirrorKeypoints(kp) {
  if (!kp) return kp;
  const out = kp.map((p) => (p ? [-p[0], p[1], p[2]] : null));
  for (const [a, b] of MIRROR_PAIRS) [out[a], out[b]] = [out[b], out[a]];
  return out;
}

export class Avatar {
  static async load(url, opts = {}) {
    const gltf = await new Promise((resolve, reject) => new GLTFLoader().load(url, resolve,
      (e) => opts.onProgress?.(e.total ? e.loaded / e.total : 0), reject));
    return new Avatar(gltf.scene, opts);
  }

  // opts.shoulderWidth: scale the model so its shoulder joints are this far apart (overlay on another rig)
  constructor(root, opts = {}) {
    this.root = root;
    this.skinMaterials = new Set();
    root.traverse((o) => {
      // clinic look: no hats / glasses (Ready Player Me accessories)
      if (/Headwear|Glasses/i.test(o.name)) o.visible = false;
      if (o.isMesh && o.visible) {
        o.castShadow = true;
        o.receiveShadow = true;
        o.frustumCulled = false; // skinned bounds don't follow the bones; avoid the mesh vanishing
        o.material = o.material.clone();
        this.skinMaterials.add(o.material);
      }
    });
    this.bones = {};
    for (const [key, names] of Object.entries(BONE_NAMES)) {
      this.bones[key] = names.map((n) => root.getObjectByName(n)).find(Boolean);
      if (!this.bones[key] && key !== 'spine1') throw new Error(`avatar rig is missing bone "${key}"`);
    }

    // Face the viewer (+Z): a model facing +Z has its right shoulder at -X.
    root.updateMatrixWorld(true);
    if (this.worldPos(this.bones.rArm).x > this.worldPos(this.bones.lArm).x) {
      root.rotateY(Math.PI);
      root.updateMatrixWorld(true);
    }
    if (opts.shoulderWidth) {
      const w = this.worldPos(this.bones.rArm).distanceTo(this.worldPos(this.bones.lArm));
      root.scale.multiplyScalar(opts.shoulderWidth / w);
      root.updateMatrixWorld(true);
    }
    // Centre the avatar so its shoulder midpoint sits at the origin, like the hub keypoints.
    const mid =this.worldPos(this.bones.rArm).add(this.worldPos(this.bones.lArm)).multiplyScalar(0.5);
    root.position.sub(mid);
    root.updateMatrixWorld(true);
    this.rest = new Map();
    for (const bone of Object.values(this.bones)) {
      if (bone) this.rest.set(bone, bone.quaternion.clone());
    }
    this.restRoot = root.quaternion.clone();

    // Start with arms down instead of the T-pose. Strap posing resets to this, not the T-pose.
    this.targets = new Map();
    this.solve(null);
    for (const [bone, q] of this.targets) bone.quaternion.copy(q);
    this.stand = new Map();
    for (const [bone, q] of this.targets) this.stand.set(bone, q.clone());
    this.standRoot = root.quaternion.clone();
    root.updateMatrixWorld(true);
    this.footY = new THREE.Box3().setFromObject(root).min.y;
  }

  worldPos(o, out = new THREE.Vector3()) { return o.getWorldPosition(out); }

  shoulderWidth() {
    this.root.updateMatrixWorld(true);
    return this.worldPos(this.bones.rArm).distanceTo(this.worldPos(this.bones.lArm));
  }

  // Rotate `bone` (from its rest pose, under the current parent) so bone->ref points along dir.
  aim(bone, ref, dir) {
    bone.quaternion.copy(this.rest.get(bone));
    bone.updateMatrixWorld(true);
    const cur = this.worldPos(ref).sub(this.worldPos(bone)).normalize();
    const delta = new THREE.Quaternion().setFromUnitVectors(cur, dir.clone().normalize());
    const world = delta.multiply(bone.getWorldQuaternion(new THREE.Quaternion()));
    const parent = bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
    bone.quaternion.copy(parent.multiply(world));
    bone.updateMatrixWorld(true);
  }

  // Pose the figure from strap directions when the phone is forwarding samples.
  // The camera keypoints stay on the skeleton overlay as the check.
  solveStrap(pose) {
    const B = this.bones;
    const saved = new Map([...this.rest.keys()].map((k) => [k, k.quaternion.clone()]));
    const savedRoot = this.root.quaternion.clone();
    const down = new THREE.Vector3(0, -1, 0);
    const dir = (v) => (v && v.length === 3 && v.some((n) => n !== 0) ? new THREE.Vector3(v[0], v[1], v[2]) : null);
    const trunk = dir(pose?.trunk);
    const upper = dir(pose?.upper_arm);
    const fore = dir(pose?.forearm);
    const right = pose?.side !== 'left';

    this.root.quaternion.copy(this.standRoot);
    this.root.updateMatrixWorld(true);
    for (const [bone, q] of this.stand) bone.quaternion.copy(q);
    this.root.updateMatrixWorld(true);

    // Lean the chest only. The spine bone on this rig also parents both thighs.
    const chest = B.spine1 || null;
    if (trunk && chest) this.aim(chest, B.neck, trunk);
    const armB = right ? B.rArm : B.lArm;
    const foreB = right ? B.rFore : B.lFore;
    const handB = right ? B.rHand : B.lHand;
    this.aim(armB, foreB, upper || down);
    this.aim(foreB, handB, fore || upper || down);

    for (const bone of this.rest.keys()) this.targets.set(bone, bone.quaternion.clone());
    this.targetRoot = this.root.quaternion.clone();
    for (const [bone, q] of saved) bone.quaternion.copy(q);
    this.root.quaternion.copy(savedRoot);
    this.root.updateMatrixWorld(true);
  }

  // Compute target bone rotations from keypoints (display frame). kp = null -> neutral standing pose.
  solve(kp) {
    const B = this.bones;
    const saved = new Map([...this.rest.keys()].map((k) => [k, k.quaternion.clone()]));
    const savedRoot = this.root.quaternion.clone();
    const ok = (...i) => kp && i.every((j) => kp[j]);
    const down = new THREE.Vector3(0, -1, 0);

    // trunk yaw from the shoulder line (left minus right should point +X when facing the viewer)
    this.root.quaternion.copy(this.restRoot);
    if (ok(KP.lSh, KP.rSh)) {
      const v = V(kp[KP.lSh]).sub(V(kp[KP.rSh]));
      const yaw = Math.atan2(-v.z, v.x);
      this.root.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), yaw));
    }
    this.root.updateMatrixWorld(true);
    for (const bone of this.rest.keys()) bone.quaternion.copy(this.rest.get(bone));
    this.root.updateMatrixWorld(true);

    if (ok(KP.lSh, KP.rSh, KP.lHip, KP.rHip)) {
      const sh = V(kp[KP.lSh]).add(V(kp[KP.rSh])).multiplyScalar(0.5);
      const hip = V(kp[KP.lHip]).add(V(kp[KP.rHip])).multiplyScalar(0.5);
      this.aim(B.spine, B.neck, sh.sub(hip));
    }
    const arm = (shI, elI, wrI, armB, foreB, handB) => {
      this.aim(armB, foreB, ok(shI, elI) ? V(kp[elI]).sub(V(kp[shI])) : down);
      this.aim(foreB, handB, ok(elI, wrI) ? V(kp[wrI]).sub(V(kp[elI])) : (ok(shI, elI) ? V(kp[elI]).sub(V(kp[shI])) : down));
    };
    arm(KP.rSh, KP.rEl, KP.rWr, B.rArm, B.rFore, B.rHand);
    arm(KP.lSh, KP.lEl, KP.lWr, B.lArm, B.lFore, B.lHand);

    for (const bone of this.rest.keys()) this.targets.set(bone, bone.quaternion.clone());
    this.targetRoot = this.root.quaternion.clone();
    for (const [bone, q] of saved) bone.quaternion.copy(q);
    this.root.quaternion.copy(savedRoot);
    this.root.updateMatrixWorld(true);
  }

  // The hub's --pose-smoothing is the only display follow. A second slerp here
  // sat about 70 ms behind the measurement.
  step(_dt) {
    for (const [bone, q] of this.targets) bone.quaternion.copy(q);
    if (this.targetRoot) this.root.quaternion.copy(this.targetRoot);
  }

  armBones(side) {
    const B = this.bones;
    return side === 'right'
      ? { shoulder: B.rShoulder, arm: B.rArm, fore: B.rFore, hand: B.rHand }
      : { shoulder: B.lShoulder, arm: B.lArm, fore: B.lFore, hand: B.lHand };
  }
}
