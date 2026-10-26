// Per-frame tracking data exported by tools/blender/device_film.py: screen positions (px) of the units/components
// for the callouts, and for the exercise shots the arm angles measured from the posed skeleton.
import product from "../public/data/product.json";
import rail from "../public/data/rail.json";
import family from "../public/data/family.json";
import reveal from "../public/data/reveal.json";
import flexion from "../public/data/flexion.json";
import abduction from "../public/data/abduction.json";
import rotation from "../public/data/rotation.json";

export type Point = [number, number, boolean];
type Frame = Record<string, Point | number | boolean>;
type Track = { shot: string; frames: Frame[] };

const TRACKS = { product, rail, family, reveal, flexion, abduction, rotation } as unknown as Record<
  string,
  Track
>;

const frameOf = (shot: string, frame: number): Frame => {
  const f = TRACKS[shot].frames;
  return f[Math.max(0, Math.min(f.length - 1, Math.round(frame)))];
};

export const point = (shot: string, key: string, frame: number): Point => frameOf(shot, frame)[key] as Point;

export const value = (shot: string, key: string, frame: number): number => frameOf(shot, frame)[key] as number;

export const series = (shot: string, key: string): number[] => TRACKS[shot].frames.map((f) => f[key] as number);
