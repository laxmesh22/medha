// Scene order and lengths (frames at 30 fps). The footage lengths match tools/blender/device_film.py LENGTHS and the
// music in tools/audio/make_soundtrack.py is 120 BPM (one beat = 15 frames): the drop lands on the reveal (12 s)
// and the outro starts at 30 s.
export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const TRANSITION = 15;

export const SCENES = [
  { id: "intro", duration: 120 },
  { id: "product", duration: 135 },
  { id: "rail", duration: 90 },
  { id: "family", duration: 75 },
  { id: "reveal", duration: 150 },
  { id: "flexion", duration: 180 },
  { id: "abduction", duration: 150 },
  { id: "rotation", duration: 120 },
  { id: "outro", duration: 150 },
] as const;

export type SceneId = (typeof SCENES)[number]["id"];

// absolute first frame of each scene in the finished film (scenes overlap by TRANSITION frames)
export const SCENE_START: Record<SceneId, number> = (() => {
  const out = {} as Record<SceneId, number>;
  let t = 0;
  SCENES.forEach((s, i) => {
    out[s.id] = t;
    t += s.duration - (i < SCENES.length - 1 ? TRANSITION : 0);
  });
  return out;
})();

export const TOTAL_FRAMES =
  SCENES.reduce((sum, s) => sum + s.duration, 0) - TRANSITION * (SCENES.length - 1);

export const duration = (id: SceneId) => SCENES.find((s) => s.id === id)!.duration;

// frame (within the rail shot) where the PB-rail latch engages: device_film.py shot_rail `click`
export const RAIL_CLICK = 59;
