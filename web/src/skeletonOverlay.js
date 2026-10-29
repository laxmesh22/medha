import * as THREE from 'three';

// Raw camera keypoints (COCO-17) as dots + lines: the "what the camera actually sees" view.
const BONES = [
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4],
];

export class SkeletonOverlay {
  constructor(scene) {
    this.group = new THREE.Group();
    this.joints = new THREE.InstancedMesh(
      new THREE.SphereGeometry(0.022, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0x0a4a4f, depthTest: false, transparent: true }),
      17,
    );
    this.joints.renderOrder = 10;
    this.pos = new Float32Array(BONES.length * 6);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    this.lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x0a4a4f, depthTest: false, transparent: true }));
    this.lines.renderOrder = 10;
    this.group.add(this.joints, this.lines);
    scene.add(this.group);
    this._m = new THREE.Matrix4();
    this._hidden = new THREE.Matrix4().makeScale(0, 0, 0);
  }

  set visible(v) { this.group.visible = v; }

  update(kp) {
    for (let i = 0; i < 17; i++) {
      const p = kp && kp[i];
      this.joints.setMatrixAt(i, p ? this._m.makeTranslation(p[0], p[1], p[2]) : this._hidden);
    }
    this.joints.instanceMatrix.needsUpdate = true;
    let n = 0;
    for (const [a, b] of BONES) {
      const pa = kp && kp[a], pb = kp && kp[b];
      if (pa && pb) { this.pos.set(pa, n * 3); this.pos.set(pb, n * 3 + 3); n += 2; }
    }
    this.lines.geometry.setDrawRange(0, n);
    this.lines.geometry.attributes.position.needsUpdate = true;
  }
}
