import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";

// Schematic of agenthandoff.md section 6: one I2C bus per unit (Qwiic colours), LiPo through the slide switch to the
// XIAO BAT pads. Drawn as a bus so nothing has to cross a device.
const W = {
  gnd: "#8f9aa1", // black in the real Qwiic cable; grey so it shows on the dark background
  v33: "#e5484d",
  sda: "#3b82f6",
  scl: "#f5c518",
  bat: "#e5484d",
  batn: "#8f9aa1",
  motor: "#c084fc",
};
const RAIL = { gnd: 90, v33: 115, sda: 140, scl: 165 } as const;
type Rail = keyof typeof RAIL;
const ease = Easing.bezier(0.33, 0, 0.2, 1);

const Wire: React.FC<{ d: string; color: string; start: number; len?: number; width?: number }> = ({ d, color, start, len = 22, width = 5 }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [start, start + len], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  return (
    <path d={d} pathLength={1} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round"
      strokeDasharray={1} strokeDashoffset={1 - p} />
  );
};

const Block: React.FC<{ x: number; y: number; w: number; h: number; title: string; sub?: string; start: number; accent?: string }> = ({
  x, y, w, h, title, sub, start, accent = C.teal,
}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [start, start + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <g opacity={o}>
      <rect x={x} y={y} width={w} height={h} rx={14} fill="rgba(255,255,255,0.05)" stroke={accent} strokeWidth={2.5} />
      <text x={x + w / 2} y={y + h / 2 - (sub ? 6 : -8)} fill={C.text} fontFamily={FONT.sans} fontWeight={700} fontSize={26} textAnchor="middle">
        {title}
      </text>
      {sub ? (
        <text x={x + w / 2} y={y + h / 2 + 28} fill={accent} fontFamily={FONT.mono} fontSize={22} textAnchor="middle">
          {sub}
        </text>
      ) : null}
    </g>
  );
};

const Dot: React.FC<{ x: number; y: number; start: number }> = ({ x, y, start }) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [start, start + 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <circle cx={x} cy={y} r={7} fill={C.text} opacity={o} />;
};

const Label: React.FC<{ x: number; y: number; text: string; start: number; anchor?: "start" | "end" | "middle"; color?: string; size?: number }> = ({
  x, y, text, start, anchor = "start", color = C.dim, size = 20,
}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [start, start + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <text x={x} y={y} fill={color} fontFamily={FONT.mono} fontSize={size} textAnchor={anchor} opacity={o}>
      {text}
    </text>
  );
};

/** Four drops from a device's top edge (GND, 3V3, SDA, SCL from left to right) up to the rails. */
const drops = (x: number, top: number, start: number) =>
  (["gnd", "v33", "sda", "scl"] as Rail[]).map((r, k) => (
    <g key={`${x}-${r}`}>
      <Wire d={`M ${x + 40 + k * 40} ${top} V ${RAIL[r]}`} color={W[r]} start={start + k * 3} len={14} />
      <Dot x={x + 40 + k * 40} y={RAIL[r]} start={start + k * 3 + 12} />
    </g>
  ));

export const WiringDiagram: React.FC<{ variant: "arm" | "waist" }> = ({ variant }) => {
  const arm = variant === "arm";
  const x0 = arm ? 0 : 260; // waist: fewer devices, centre them
  const railEnd = arm ? 1140 : 960;
  return (
    <svg width={1200} height={800} viewBox="0 0 1200 800" style={{ position: "absolute", left: 60, top: 150, overflow: "visible" }}>
      {/* rails */}
      {(["gnd", "v33", "sda", "scl"] as Rail[]).map((r, k) => (
        <g key={r}>
          <Wire d={`M ${x0 + 10} ${RAIL[r]} H ${railEnd}`} color={W[r]} start={4 + k * 3} len={26} />
          <Label x={railEnd + 14} y={RAIL[r] + 7} text={{ gnd: "GND", v33: "3V3", sda: "SDA", scl: "SCL" }[r]} start={20} color={W[r]} />
        </g>
      ))}
      {arm ? (
        <>
          <Block x={x0 + 10} y={230} w={220} h={150} title="BNO085" sub="forearm · 0x4B" start={30} />
          {drops(x0 + 10, 230, 44)}
          <Label x={x0 + 120} y={410} text="30 cm Qwiic lead" start={50} anchor="middle" />
          <Block x={x0 + 270} y={230} w={220} h={150} title="BNO085" sub="upper arm · 0x4A" start={34} />
          {drops(x0 + 270, 230, 50)}
        </>
      ) : (
        <>
          <Block x={x0 + 10} y={230} w={220} h={150} title="BNO085" sub="waist · 0x4A" start={30} />
          {drops(x0 + 10, 230, 44)}
        </>
      )}
      {/* XIAO ESP32-S3: D4/D5 on the left edge, GND/3V3 on the right edge, BAT pads underneath */}
      <Block x={x0 + 570} y={210} w={230} h={280} title="XIAO ESP32-S3" sub="BLE" start={38} accent="#9ad1c2" />
      <Label x={x0 + 580} y={268} text="D4" start={56} color={C.text} />
      <Label x={x0 + 580} y={298} text="D5" start={56} color={C.text} />
      <Label x={x0 + 790} y={248} text="GND" start={56} color={C.text} anchor="end" />
      <Label x={x0 + 790} y={288} text="3V3" start={56} color={C.text} anchor="end" />
      <Wire d={`M ${x0 + 570} 260 H ${x0 + 545} V ${RAIL.sda}`} color={W.sda} start={62} />
      <Dot x={x0 + 545} y={RAIL.sda} start={80} />
      <Wire d={`M ${x0 + 570} 290 H ${x0 + 525} V ${RAIL.scl}`} color={W.scl} start={66} />
      <Dot x={x0 + 525} y={RAIL.scl} start={84} />
      <Wire d={`M ${x0 + 800} 240 H ${x0 + 825} V ${RAIL.gnd}`} color={W.gnd} start={62} />
      <Dot x={x0 + 825} y={RAIL.gnd} start={80} />
      <Wire d={`M ${x0 + 800} 280 H ${x0 + 845} V ${RAIL.v33}`} color={W.v33} start={66} />
      <Dot x={x0 + 845} y={RAIL.v33} start={84} />
      {arm ? (
        <>
          <Block x={x0 + 900} y={230} w={220} h={150} title="DRV2605L" sub="haptics · 0x5A" start={42} />
          {drops(x0 + 900, 230, 58)}
          <circle cx={x0 + 1010} cy={480} r={36} fill="rgba(192,132,252,0.12)" stroke={W.motor} strokeWidth={2.5} />
          <Label x={x0 + 1010} y={486} text="ERM" start={70} anchor="middle" color={C.text} />
          <Wire d={`M ${x0 + 985} 380 V 452`} color={W.motor} start={74} len={10} />
          <Wire d={`M ${x0 + 1035} 380 V 452`} color={W.motor} start={76} len={10} />
          <Label x={x0 + 1060} y={436} text="OUT+/−" start={80} />
        </>
      ) : null}
      {/* battery: LiPo + -> slide switch -> BAT+, LiPo - -> BAT- */}
      <Block x={x0 + 400} y={600} w={230} h={110} title="LiPo 500 mAh" sub="PCM protected" start={90} accent={C.amber} />
      <Block x={x0 + 690} y={615} w={120} h={70} title="Switch" start={94} accent={C.amber} />
      <Wire d={`M ${x0 + 630} 630 H ${x0 + 690}`} color={W.bat} start={100} len={10} />
      <Wire d={`M ${x0 + 810} 645 H ${x0 + 840} V 560 H ${x0 + 640} V 490`} color={W.bat} start={108} />
      <Wire d={`M ${x0 + 630} 685 H ${x0 + 660} V 740 H ${x0 + 880} V 530 H ${x0 + 760} V 490`} color={W.batn} start={112} />
      <Label x={x0 + 628} y={518} text="BAT+" start={124} color={C.text} anchor="end" />
      <Label x={x0 + 772} y={518} text="BAT−" start={124} color={C.text} anchor="start" />
      <Label x={x0 + 10} y={785} text="Optional: 100k / 100k divider from BAT+ to D1 for the battery level" start={130} size={22} />
    </svg>
  );
};
