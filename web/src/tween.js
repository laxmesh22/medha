// Tiny easing tween (CodePen-style smooth transitions without an extra dependency; works offline).
const active = new WeakMap();

const easeInOutCubic = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);

export function tween(obj, key, to, ms = 700) {
  let tokens = active.get(obj);
  if (!tokens) active.set(obj, (tokens = {}));
  const token = (tokens[key] = Symbol(key));
  const from = obj[key];
  if (!(ms > 0)) { obj[key] = to; return Promise.resolve(true); }
  const t0 = performance.now();
  return new Promise((resolve) => {
    const step = (now) => {
      if (tokens[key] !== token) return resolve(false); // superseded by a newer tween
      const k = Math.min(1, (now - t0) / ms);
      obj[key] = from + (to - from) * easeInOutCubic(k);
      if (k < 1) requestAnimationFrame(step);
      else resolve(true);
    };
    requestAnimationFrame(step);
  });
}

// Fade a material, switching transparency/depth-write so opaque parts stay crisp.
export function fadeMaterial(mat, opacity, ms = 700) {
  mat.visible = true;
  mat.transparent = true;
  mat.depthWrite = opacity > 0.95;
  mat.needsUpdate = true;
  return tween(mat, 'opacity', opacity, ms).then((done) => {
    if (!done) return;
    if (opacity >= 0.999) { mat.transparent = false; mat.needsUpdate = true; }
    if (opacity <= 0.01) mat.visible = false;
  });
}
