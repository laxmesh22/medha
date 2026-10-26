// Callout positions exported by tools/blender/assembly_guide.py (public/guide/<clip>.json) and, for the two shots
// reused from the film, by device_film.py (public/data/<shot>.json via ../track).
import kit from "../../public/guide/kit.json";
import neoprene from "../../public/guide/neoprene.json";
import bno from "../../public/guide/bno.json";
import motor from "../../public/guide/motor.json";
import sw from "../../public/guide/switch.json";
import xiao from "../../public/guide/xiao.json";
import wires from "../../public/guide/wires.json";
import deck from "../../public/guide/deck.json";
import top from "../../public/guide/top.json";
import lid from "../../public/guide/lid.json";
import forearm from "../../public/guide/forearm.json";
import waist from "../../public/guide/waist.json";
import strap from "../../public/guide/strap.json";
import charge from "../../public/guide/charge.json";
import power from "../../public/guide/power.json";
import { point as filmPoint } from "../track";

type Pt = [number, number, boolean];
type Clip = { frames: Record<string, Pt>[] };

const CLIPS = { kit, neoprene, bno, motor, switch: sw, xiao, wires, deck, top, lid, forearm, waist, strap, charge, power } as unknown as Record<
  string,
  Clip
>;

export const guidePoint = (clip: string, key: string, frame: number, source: "guide" | "film" = "guide"): Pt => {
  if (source === "film") return filmPoint(clip, key, frame);
  const f = CLIPS[clip].frames;
  const row = f[Math.max(0, Math.min(f.length - 1, Math.round(frame)))];
  return row[key] ?? [0, 0, false];
};

export const hasGuideKey = (clip: string, key: string) => !!CLIPS[clip]?.frames[0]?.[key];
