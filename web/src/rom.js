import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// Range-of-motion overlay at the affected shoulder:
//   * filled arc from the trunk's "down" axis to the current upper-arm direction
//   * translucent ghost arm at the clinician's target angle, in the current plane of movement
//   * floating label with the hub's TRUE elevation (or "unavailable")
const SEG = 40;

export class RomOverlay {
  constructor(scene) {
    this.scene = scene;
    this.radius = 0.24;
    this.target = 120;

    this.fanPos = new Float32Array((SEG + 2) * 3);
    const fanGeo = new THREE.BufferGeometry();
    fanGeo.setAttribute('position', new THREE.BufferAttribute(this.fanPos, 3));
    const idx = [];
    for (let i = 1; i <= SEG; i++) idx.push(0, i, i + 1);
    fanGeo.setIndex(idx);
    this.fanMat = new THREE.MeshBasicMaterial({ color: 0x16a34a, transparent: true, opacity: 0.28, side: THREE.DoubleSide, depthWrite: false });
    this.fan = new THREE.Mesh(fanGeo, this.fanMat);
    this.fan.renderOrder = 5;

    this.edgePos = new Float32Array((SEG + 1) * 3);
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute('position', new THREE.BufferAttribute(this.edgePos, 3));
    this.edgeMat = new THREE.LineBasicMaterial({ color: 0x16a34a });
    this.edge = new THREE.Line(edgeGeo, this.edgeMat);

    this.ghostMat = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.22, depthWrite: false, emissive: 0x4fc6a6, emissiveIntensity: 0 });
    this.ghost = new THREE.Mesh(new THREE.CapsuleGeometry(0.035, 0.5, 4, 12), this.ghostMat);

    this.labelEl = document.createElement('div');
    this.labelEl.className = 'rom-label';
    this.label = new CSS2DObject(this.labelEl);

    this.group = new THREE.Group();
    this.group.add(this.fan, this.edge, this.ghost, this.label);
    scene.add(this.group);
  }

  set visible(v) { this.group.visible = v; }

  // shoulder, elbow, trunkTop, trunkBottom: world positions from the avatar's bones.
  update({ shoulder, elbow, trunkTop, trunkBottom, angles, colour }) {
    const down = trunkBottom.clone().sub(trunkTop).normalize();
    const u = elbow.clone().sub(shoulder).normalize();
    let axis = new THREE.Vector3().crossVectors(down, u);
    const ang = down.angleTo(u);
    if (axis.lengthSq() < 1e-6) axis.set(1, 0, 0); // arm along the trunk: arc plane is arbitrary
    axis.normalize();

    this.fanPos.set(shoulder.toArray(), 0);
    const q = new THREE.Quaternion();
    const p = new THREE.Vector3();
    for (let i = 0; i <= SEG; i++) {
      q.setFromAxisAngle(axis, (ang * i) / SEG);
      p.copy(down).applyQuaternion(q).multiplyScalar(this.radius).add(shoulder);
      this.fanPos.set(p.toArray(), (i + 1) * 3);
      this.edgePos.set(p.toArray(), i * 3);
    }
    this.fan.geometry.attributes.position.needsUpdate = true;
    this.edge.geometry.attributes.position.needsUpdate = true;
    this.fan.geometry.computeBoundingSphere();
    this.edge.geometry.computeBoundingSphere();
    this.fanMat.color.set(colour);
    this.edgeMat.color.set(colour);
    const show = ang > THREE.MathUtils.degToRad(4);
    this.fan.visible = this.edge.visible = show;

    // ghost: target angle in the current plane (or the flexion plane when the arm is down)
    let gAxis = axis;
    if (ang < THREE.MathUtils.degToRad(15)) {
      const anterior = new THREE.Vector3(0, 0, 1);
      gAxis = new THREE.Vector3().crossVectors(down, anterior).normalize();
    }
    const gDir = down.clone().applyQuaternion(new THREE.Quaternion().setFromAxisAngle(gAxis, THREE.MathUtils.degToRad(this.target)));
    this.ghost.position.copy(shoulder).addScaledVector(gDir, 0.29);
    this.ghost.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), gDir);
    const e = angles?.elevation?.value;
    const reached = e != null && e >= this.target - 5;
    this.ghostMat.emissiveIntensity = reached ? 0.9 : 0;
    this.ghostMat.opacity = reached ? 0.4 : 0.22;

    this.label.position.copy(shoulder).add(new THREE.Vector3(0, 0.16, 0));
    this.labelEl.textContent = e != null ? `${Math.round(e)}°` : 'unavailable';
    this.labelEl.dataset.state = e == null ? 'na' : reached ? 'reached' : 'live';
    return reached;
  }
}
