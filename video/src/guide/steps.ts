// Assembly guide content. Every instruction matches the CAD (hardware/cad/physio_pod.py, hardware/README.md) and
// the wiring in agenthandoff.md section 6. Clip lengths match LENGTHS in tools/blender/assembly_guide.py.

export type CalloutSpec = { key: string; label: string; sub?: string; dx: number; dy: number; start: number; end?: number };

export type Step = {
  id: string;
  kind: "clip" | "card" | "wiring" | "wiring-waist";
  clip?: string; // footage name (guide/footage/<clip>.mp4 or footage/<clip>.mp4 for film shots)
  source?: "guide" | "film";
  clipFrames?: number;
  hold: number; // frames the last frame (or the card) stays up after the clip
  section: string;
  title: string;
  bullets: string[];
  need?: string[];
  warn?: string;
  callouts?: CalloutSpec[];
  tags?: { key: string; label: string }[]; // small name tags pinned to parts (kit layout)
};

export const GUIDE_FPS = 30;
export const GUIDE_FADE = 10;

export const STEPS: Step[] = [
  {
    id: "title",
    kind: "card",
    hold: 150,
    section: "Assembly guide",
    title: "Build a Physio Buddy set",
    bullets: ["Upper-arm unit (IMU + haptics)", "Forearm unit (IMU)", "Waist unit (IMU, body reference)"],
  },
  {
    id: "before",
    kind: "card",
    hold: 270,
    section: "Before you start",
    title: "No screws needed",
    bullets: [
      "The lid clicks on, the pod clicks onto its rail, boards sit on rails and foam tape",
      "Print in PETG (PLA works): 0.2 mm layers, 3 walls, 25 % gyroid",
      "Tools: soldering iron, flush cutters, tweezers, wire strippers, multimeter",
      "Consumables: 28–30 AWG silicone wire, heat-shrink, 1 mm foam tape, contact adhesive",
    ],
    warn: "PCM-protected LiPo cells only. Check polarity before connecting. Never charge while worn.",
  },
  {
    id: "kit",
    kind: "clip",
    clip: "kit",
    source: "guide",
    clipFrames: 110,
    hold: 150,
    section: "Upper-arm unit",
    title: "Lay out the kit",
    bullets: ["Printed: strap base, pod body, deck, lid", "Electronics: BNO085, XIAO ESP32-S3, DRV2605L, coin motor, switch, LiPo"],
    need: ["foam tape", "velcro 25 mm", "neoprene 1 mm", "Qwiic cable 30 cm"],
    tags: [
      { key: "base", label: "Strap base" },
      { key: "body", label: "Pod body" },
      { key: "deck", label: "Deck" },
      { key: "lid", label: "Lid" },
      { key: "lipo", label: "LiPo" },
      { key: "bno085", label: "BNO085" },
      { key: "xiao", label: "XIAO" },
      { key: "drv2605", label: "DRV2605L" },
      { key: "motor", label: "Motor" },
      { key: "switch", label: "Switch" },
      { key: "foam", label: "Foam tape" },
      { key: "neoprene", label: "Neoprene" },
      { key: "velcro", label: "Velcro" },
      { key: "qwiic", label: "Qwiic lead" },
    ],
  },
  {
    id: "wiring",
    kind: "wiring",
    hold: 390,
    section: "Upper-arm unit",
    title: "Solder the harness first",
    bullets: [
      "I2C bus: SDA → D4, SCL → D5, 3V3 and GND from the XIAO",
      "Upper-arm BNO085 0x4A, forearm BNO085 0x4B, DRV2605L 0x5A",
      "Boards differ in default address: set each one with its ADR jumper",
      "LiPo + → slide switch → BAT+ pad; LiPo − → BAT− pad (underside)",
    ],
    warn: "Check the XIAO pinout on the Seeed wiki before soldering.",
  },
  {
    id: "neoprene",
    kind: "clip",
    clip: "neoprene",
    source: "guide",
    clipFrames: 70,
    hold: 120,
    section: "Upper-arm unit",
    title: "Line the base",
    bullets: ["Glue a 1 mm neoprene strip under the curved base", "It stops the base sliding on skin"],
    need: ["neoprene 1 mm", "contact adhesive"],
    callouts: [{ key: "strip", label: "Neoprene 1 mm", dx: -260, dy: -80, start: 24, end: 50 }],
  },
  {
    id: "bno",
    kind: "clip",
    clip: "bno",
    source: "guide",
    clipFrames: 70,
    hold: 120,
    section: "Upper-arm unit",
    title: "BNO085 on its pads",
    bullets: ["Foam tape on the four corner pads", "Press the board down: the side ribs hold it", "The sensor must not move inside the pod"],
    need: ["BNO085", "foam tape"],
    callouts: [{ key: "bno085", label: "BNO085 IMU", sub: "0x4A", dx: -280, dy: -110, start: 50 }],
  },
  {
    id: "motor",
    kind: "clip",
    clip: "motor",
    source: "guide",
    clipFrames: 55,
    hold: 100,
    section: "Upper-arm unit",
    title: "Coin motor in its pocket",
    bullets: ["Adhesive side down into the floor pocket", "It sits under the XIAO; leads go up the side wall"],
    need: ["10 mm ERM coin motor"],
    callouts: [{ key: "motor", label: "Coin motor", sub: "10 × 2.7 mm", dx: -260, dy: -120, start: 34 }],
  },
  {
    id: "switch",
    kind: "clip",
    clip: "switch",
    source: "guide",
    clipFrames: 55,
    hold: 100,
    section: "Upper-arm unit",
    title: "Slide switch",
    bullets: ["Lever through the slot in the end wall", "It cuts LiPo + before the BAT+ pad"],
    need: ["SS-12D00 switch"],
    callouts: [{ key: "switch", label: "SS-12D00", sub: "lever through the wall", dx: -240, dy: -120, start: 36 }],
  },
  {
    id: "xiao",
    kind: "clip",
    clip: "xiao",
    source: "guide",
    clipFrames: 75,
    hold: 110,
    section: "Upper-arm unit",
    title: "XIAO onto its rails",
    bullets: ["Drop it onto the rails, components up", "Slide it toward the end wall until USB-C sits in the opening"],
    need: ["XIAO ESP32-S3"],
    callouts: [{ key: "usb", label: "USB-C opening", dx: 120, dy: -170, start: 58 }],
  },
  {
    id: "wires",
    kind: "clip",
    clip: "wires",
    source: "guide",
    clipFrames: 90,
    hold: 130,
    section: "Upper-arm unit",
    title: "Route the bottom layer",
    bullets: [
      "BNO085 → XIAO: blue/yellow to D4/D5, red/black to 3V3/GND",
      "Switch → BAT+ under the XIAO",
      "Qwiic lead out through the grommet to the forearm",
    ],
    callouts: [{ key: "grommet", label: "Cable grommet", sub: "to the forearm pod", dx: -200, dy: 130, start: 80 }],
  },
  {
    id: "deck",
    kind: "clip",
    clip: "deck",
    source: "guide",
    clipFrames: 50,
    hold: 90,
    section: "Upper-arm unit",
    title: "Deck in",
    bullets: ["It rests on the ledges along both long walls", "Wires stay underneath, leads come up at the ends"],
    need: ["printed deck"],
  },
  {
    id: "top",
    kind: "clip",
    clip: "top",
    source: "guide",
    clipFrames: 95,
    hold: 140,
    section: "Upper-arm unit",
    title: "LiPo and haptic driver",
    bullets: [
      "Foam tape, then LiPo and DRV2605L on the deck",
      "LiPo red → switch, black → BAT−",
      "Motor leads → DRV2605L OUT; DRV I2C on the same bus",
    ],
    need: ["500 mAh LiPo (752530)", "DRV2605L"],
    warn: "Don't let the LiPo leads touch while soldering.",
    callouts: [
      { key: "lipo", label: "500 mAh LiPo", dx: -60, dy: -230, start: 40 },
      { key: "drv2605", label: "DRV2605L", sub: "0x5A", dx: -40, dy: -290, start: 52 },
    ],
  },
  {
    id: "lid",
    kind: "clip",
    clip: "lid",
    source: "guide",
    clipFrames: 60,
    hold: 120,
    section: "Upper-arm unit",
    title: "Click the lid on",
    bullets: ["Arrow toward the shoulder (cable exit faces the elbow)", "Press until both sides click", "Pry notch at the end to open it again"],
    need: ["PB-ARM lid"],
  },
  {
    id: "forearm",
    kind: "clip",
    clip: "forearm",
    source: "guide",
    clipFrames: 110,
    hold: 130,
    section: "Forearm unit",
    title: "Forearm pod",
    bullets: ["BNO085 (set to 0x4B) on foam pads", "Qwiic lead in through the grommet, plug into the board", "PB-FORE lid: arrow toward the wrist"],
    need: ["BNO085 (0x4B)", "PB-FORE lid"],
    callouts: [{ key: "grommet", label: "Qwiic lead in", dx: -220, dy: 120, start: 60 }],
  },
  {
    id: "wiring-waist",
    kind: "wiring-waist",
    hold: 210,
    section: "Waist unit",
    title: "Waist harness",
    bullets: ["Its own XIAO, BNO085 (0x4A), LiPo and switch", "No haptic driver, no motor", "Same pod body and deck as the arm"],
  },
  {
    id: "waist",
    kind: "clip",
    clip: "waist",
    source: "guide",
    clipFrames: 100,
    hold: 110,
    section: "Waist unit",
    title: "Waist pod",
    bullets: ["Same order: pads + BNO085, switch, XIAO, deck, LiPo", "PB-WAIST lid: arrow up"],
    need: ["PB-WAIST lid", "40 mm belt"],
  },
  {
    id: "strap",
    kind: "clip",
    clip: "strap",
    source: "guide",
    clipFrames: 120,
    hold: 140,
    section: "Straps",
    title: "Thread the strap",
    bullets: [
      "Up through one slot, fold back and fasten",
      "Round the limb, up through the other slot, fold back",
      "Snug, not tight: the base must not rotate",
    ],
    need: ["velcro 25 mm (arm, forearm)", "40 mm belt (waist)"],
    callouts: [
      { key: "slot_l", label: "Strap slot", dx: -220, dy: -150, start: 20 },
      { key: "slot_r", label: "Strap slot", dx: 120, dy: -190, start: 70 },
    ],
  },
  {
    id: "rail",
    kind: "clip",
    clip: "rail",
    source: "film",
    clipFrames: 90,
    hold: 120,
    section: "Mount",
    title: "Click the pod onto the rail",
    bullets: ["Slide in from the open end until it clicks", "Every pod fits every base", "To remove: press the tab under the open end"],
  },
  {
    id: "wear",
    kind: "clip",
    clip: "reveal",
    source: "film",
    clipFrames: 150,
    hold: 150,
    section: "Wear",
    title: "Where each unit goes",
    bullets: [
      "Upper arm: outer side, mid-humerus, arrow to the shoulder",
      "Forearm: back of the forearm near the wrist, arrow to the wrist",
      "Waist: belt at the navel line, arrow up",
    ],
    warn: "Same place, same way round, every session.",
    callouts: [
      { key: "upperarm", label: "Upper arm", sub: "arrow → shoulder", dx: -200, dy: -90, start: 40 },
      { key: "forearm", label: "Forearm", sub: "arrow → wrist", dx: -170, dy: 30, start: 52 },
      { key: "trunk", label: "Waist", sub: "arrow up", dx: -320, dy: 230, start: 64 },
    ],
  },
  {
    id: "charge",
    kind: "clip",
    clip: "charge",
    source: "guide",
    clipFrames: 70,
    hold: 120,
    section: "Charge",
    title: "Charge off the body",
    bullets: ["Take the pod off its base", "USB-C into the end wall; the XIAO charges the LiPo (~100 mA)", "Roughly 5–6 h from empty"],
    warn: "Never charge while worn.",
    callouts: [{ key: "usb", label: "USB-C", dx: -200, dy: -140, start: 40 }],
  },
  {
    id: "power",
    kind: "clip",
    clip: "power",
    source: "guide",
    clipFrames: 50,
    hold: 110,
    section: "Power on",
    title: "Switch on and check",
    bullets: ["Slide the lever to on", "Arm and waist units appear on the station (the forearm pod reports through the arm unit)", "Calibrate when the station asks"],
    callouts: [{ key: "lever", label: "On / off", dx: 160, dy: -150, start: 22 }],
  },
  {
    id: "done",
    kind: "card",
    hold: 180,
    section: "Checklist",
    title: "Ready for a session",
    bullets: [
      "Sensors don't move inside the pods",
      "Arrows: shoulder, wrist, up",
      "Straps snug, bases don't rotate",
      "Arm and waist units connected on the station",
    ],
  },
];

export const stepFrames = (s: Step) => (s.clipFrames ?? 0) + s.hold;

export const GUIDE_TOTAL = STEPS.reduce((n, s) => n + stepFrames(s), 0) - GUIDE_FADE * (STEPS.length - 1);

export const GUIDE_START: Record<string, number> = (() => {
  const out: Record<string, number> = {};
  let t = 0;
  STEPS.forEach((s) => {
    out[s.id] = t;
    t += stepFrames(s) - GUIDE_FADE;
  });
  return out;
})();

// numbered build steps (cards are not counted)
export const BUILD_STEPS = STEPS.filter((s) => s.kind !== "card");
