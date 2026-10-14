import * as THREE from 'three';

// Procedural materials for the real-anatomy model. Each one injects GLSL into a MeshPhysicalMaterial,
// so lighting, shadows and SKINNING all keep working. Patterns are computed from the bind-pose position
// (`position` attribute), so muscle fibres stay glued to the tissue as it moves.

const NOISE = /* glsl */ `
float pbHash(vec3 p){ p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float pbNoise(vec3 x){
  vec3 i = floor(x); vec3 f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(pbHash(i + vec3(0,0,0)), pbHash(i + vec3(1,0,0)), f.x),
                 mix(pbHash(i + vec3(0,1,0)), pbHash(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(pbHash(i + vec3(0,0,1)), pbHash(i + vec3(1,0,1)), f.x),
                 mix(pbHash(i + vec3(0,1,1)), pbHash(i + vec3(1,1,1)), f.x), f.y), f.z);
}`;

function inject(mat, { uniforms, vertexHead = '', vertexBody = '', fragmentHead = '', colorBody = '', emissiveBody = '', key }) {
  mat.userData.uniforms = uniforms;
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vPb;\n${vertexHead}`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>\nvPb = position;\n${vertexBody}`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vPb;\n${NOISE}\n${fragmentHead}`)
      .replace('#include <color_fragment>', `#include <color_fragment>\n${colorBody}`)
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>\n${emissiveBody}`);
  };
  mat.customProgramCacheKey = () => key;
  return mat;
}

// Principal axis of a mesh (PCA of bind-pose vertices) = the muscle's main fibre direction.
export function principalAxis(geometry) {
  const p = geometry.attributes.position;
  const n = p.count;
  const c = new THREE.Vector3();
  for (let i = 0; i < n; i++) c.add(new THREE.Vector3().fromBufferAttribute(p, i));
  c.divideScalar(n);
  const C = [0, 0, 0, 0, 0, 0]; // xx xy xz yy yz zz
  const v = new THREE.Vector3();
  for (let i = 0; i < n; i++) {
    v.fromBufferAttribute(p, i).sub(c);
    C[0] += v.x * v.x; C[1] += v.x * v.y; C[2] += v.x * v.z; C[3] += v.y * v.y; C[4] += v.y * v.z; C[5] += v.z * v.z;
  }
  let a = new THREE.Vector3(1, 1, 1).normalize();
  for (let k = 0; k < 30; k++) { // power iteration
    a = new THREE.Vector3(C[0] * a.x + C[1] * a.y + C[2] * a.z, C[1] * a.x + C[3] * a.y + C[4] * a.z,
      C[2] * a.x + C[4] * a.y + C[5] * a.z).normalize();
  }
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < n; i++) {
    const t = v.fromBufferAttribute(p, i).sub(c).dot(a);
    lo = Math.min(lo, t); hi = Math.max(hi, t);
  }
  const u = new THREE.Vector3().crossVectors(a, Math.abs(a.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0)).normalize();
  const w = new THREE.Vector3().crossVectors(a, u);
  return { centre: c, axis: a, u, w, lo, hi };
}

// Skeletal muscle: dark-red fascicles running along the fibre axis, pearly tendon at both ends,
// moist clearcoat. uActive (0..1) = "this muscle is working" glow.
export function muscleMaterial(geometry) {
  const ax = principalAxis(geometry);
  const uniforms = {
    uAxis: { value: ax.axis }, uU: { value: ax.u }, uW: { value: ax.w }, uCentre: { value: ax.centre },
    uRange: { value: new THREE.Vector2(ax.lo, ax.hi) }, uActive: { value: 0 }, uTime: { value: 0 },
  };
  const mat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff, roughness: 0.48, clearcoat: 0.35, clearcoatRoughness: 0.35, sheen: 0.4,
    sheenColor: new THREE.Color(0xff9a8a), transparent: true, opacity: 1,
  });
  return inject(mat, {
    key: 'pb-muscle',
    uniforms,
    fragmentHead: 'uniform vec3 uAxis, uU, uW, uCentre; uniform vec2 uRange; uniform float uActive, uTime;',
    colorBody: /* glsl */ `
      vec3 pbRel = vPb - uCentre;
      float pbAlong = (dot(pbRel, uAxis) - uRange.x) / max(uRange.y - uRange.x, 1e-4);
      vec3 pbQ = vec3(dot(pbRel, uU) * 520.0, dot(pbRel, uW) * 520.0, dot(pbRel, uAxis) * 22.0);
      float pbN = pbNoise(pbQ) * 0.62 + pbNoise(pbQ * 2.07 + 3.1) * 0.38;
      float pbFibre = smoothstep(0.28, 0.78, pbN);
      vec3 pbMeat = mix(vec3(0.36, 0.045, 0.05), vec3(0.80, 0.20, 0.17), pbFibre);
      float pbTendon = 1.0 - smoothstep(0.03, 0.14, min(pbAlong, 1.0 - pbAlong));
      diffuseColor.rgb = mix(pbMeat, vec3(0.93, 0.89, 0.80), pbTendon);`,
    emissiveBody: /* glsl */ `
      float pbPulse = 0.75 + 0.25 * sin(uTime * 5.0 + dot(vPb, uAxis) * 40.0);
      totalEmissiveRadiance += vec3(1.0, 0.55, 0.12) * uActive * 0.85 * pbPulse * (0.5 + 0.5 * pbFibre);`,
  });
}

// Bone: ivory with subtle porous variation.
export function boneMaterial() {
  const mat = new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.62, clearcoat: 0.12, transparent: true });
  return inject(mat, {
    key: 'pb-bone',
    uniforms: {},
    colorBody: /* glsl */ `
      float pbN = pbNoise(vPb * 180.0) * 0.6 + pbNoise(vPb * 37.0) * 0.4;
      diffuseColor.rgb = mix(vec3(0.80, 0.74, 0.62), vec3(0.96, 0.93, 0.86), pbN);`,
  });
}

// Joint capsule / ligament: translucent pearly connective tissue. aRegion (vec4) = membership of the
// superior / inferior / anterior / posterior capsule; uStretch (vec4) = how much each region is stretched.
export function capsuleMaterial(geometry, highlight) {
  if (highlight) addCapsuleRegions(geometry);
  const uniforms = { uStretch: { value: new THREE.Vector4() }, uTime: { value: 0 } };
  const mat = new THREE.MeshPhysicalMaterial({
    color: 0xdfe8f5, roughness: 0.3, transmission: 0, clearcoat: 0.6, transparent: true, opacity: 0.85,
    side: THREE.DoubleSide, depthWrite: false,
  });
  if (!highlight) return mat;
  return inject(mat, {
    key: 'pb-capsule',
    uniforms,
    vertexHead: 'attribute vec4 aRegion; varying vec4 vRegion;',
    vertexBody: 'vRegion = aRegion;',
    fragmentHead: 'uniform vec4 uStretch; uniform float uTime; varying vec4 vRegion;',
    colorBody: 'float pbS = clamp(dot(vRegion, uStretch), 0.0, 1.0); diffuseColor.rgb = mix(diffuseColor.rgb, vec3(1.0, 0.62, 0.12), pbS);',
    emissiveBody: 'totalEmissiveRadiance += vec3(1.0, 0.5, 0.05) * pbS * (0.9 + 0.35 * sin(uTime * 6.0));',
  });
}

function addCapsuleRegions(geometry) {
  geometry.computeBoundingBox();
  const c = geometry.boundingBox.getCenter(new THREE.Vector3());
  const p = geometry.attributes.position;
  const reg = new Float32Array(p.count * 4);
  const v = new THREE.Vector3();
  const s = (e0, e1, x) => { const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); };
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i).sub(c).normalize();
    // model faces +Z: superior +Y, inferior -Y, anterior +Z, posterior -Z
    reg.set([s(0.2, 0.75, v.y), s(0.2, 0.75, -v.y), s(0.15, 0.7, v.z), s(0.15, 0.7, -v.z)], i * 4);
  }
  geometry.setAttribute('aRegion', new THREE.BufferAttribute(reg, 4));
}
