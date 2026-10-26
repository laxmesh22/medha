import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { series } from "../track";

const ease = Easing.bezier(0.16, 1, 0.3, 1);

const polar = (cx: number, cy: number, r: number, deg: number): [number, number] => {
  // 0 deg = arm down (pointing at 6 o'clock), 180 = overhead; the gauge sweeps through 9 o'clock
  const a = ((90 + deg) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
};

const arc = (cx: number, cy: number, r: number, a0: number, a1: number) => {
  const [x0, y0] = polar(cx, cy, r, a0);
  const [x1, y1] = polar(cx, cy, r, a1);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
};

/** Live angle panel: the value is measured from the posed skeleton in Blender (geometry), like the station does. */
export const AngleHud: React.FC<{ shot: string; field: "elevation" | "rotation"; exercise: string; source: string; max: number }> = ({
  shot,
  field,
  exercise,
  source,
  max,
}) => {
  const frame = useCurrentFrame();
  const data = series(shot, field);
  const i = Math.max(0, Math.min(data.length - 1, Math.round(frame)));
  const v = data[i];
  const peak = Math.max(...data.slice(0, i + 1));
  const inT = interpolate(frame, [6, 26], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const out = interpolate(frame, [data.length - 20, data.length - 6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const cx = 200;
  const cy = 195;
  const r = 160;
  const shown = Math.max(0, Math.min(max, v));
  const [nx, ny] = polar(cx, cy, r, shown);
  const [px, py] = polar(cx, cy, r + 22, Math.min(max, peak));
  // sparkline of the trace so far
  const sw = 440;
  const sh = 110;
  const pts = data
    .slice(0, i + 1)
    .map((d, k) => `${(k / (data.length - 1)) * sw},${sh - (Math.max(0, d) / max) * sh}`)
    .join(" ");
  const blink = Math.floor(frame / 15) % 2 === 0;
  return (
    <div
      style={{
        position: "absolute",
        left: 110,
        top: 120,
        width: 520,
        padding: "34px 40px 36px",
        background: C.panel,
        border: `1px solid ${C.line}`,
        borderRadius: 18,
        backdropFilter: "blur(10px)",
        opacity: inT * out,
        translate: `${(1 - inT) * -40}px 0px`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14, fontFamily: FONT.mono, fontSize: 22, letterSpacing: 4, color: C.teal }}>
        <span style={{ width: 14, height: 14, borderRadius: 7, background: blink ? C.teal : "transparent", border: `2px solid ${C.teal}` }} />
        LIVE · {source}
      </div>
      <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 50, color: C.text, marginTop: 14, lineHeight: 1.05 }}>{exercise}</div>
      <svg width={440} height={390} style={{ marginTop: 10, overflow: "visible" }}>
        <path d={arc(cx, cy, r, 0, max)} stroke="rgba(255,255,255,0.12)" strokeWidth={18} fill="none" strokeLinecap="round" />
        {Array.from({ length: Math.floor(max / 30) + 1 }, (_, k) => k * 30).map((d) => {
          const [x0, y0] = polar(cx, cy, r - 22, d);
          const [x1, y1] = polar(cx, cy, r - 34, d);
          const [tx, ty] = polar(cx, cy, r - 58, d);
          return (
            <g key={d}>
              <line x1={x0} y1={y0} x2={x1} y2={y1} stroke={C.dim} strokeWidth={2} />
              <text x={tx} y={ty + 7} fill={C.dim} fontSize={20} fontFamily={FONT.mono} textAnchor="middle">
                {d}
              </text>
            </g>
          );
        })}
        {shown > 0.5 ? <path d={arc(cx, cy, r, 0, shown)} stroke={C.teal} strokeWidth={18} fill="none" strokeLinecap="round" /> : null}
        <circle cx={nx} cy={ny} r={13} fill={C.text} stroke={C.teal} strokeWidth={4} />
        <circle cx={px} cy={py} r={6} fill={C.amber} />
        <text x={cx + 20} y={cy + 8} fill={C.text} fontSize={112} fontFamily={FONT.mono} fontWeight={700} textAnchor="start">
          {Math.round(v)}°
        </text>
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: FONT.mono, fontSize: 22, color: C.dim, marginTop: 8 }}>
        <span>angle trace</span>
        <span style={{ color: C.amber }}>peak {Math.round(peak)}°</span>
      </div>
      <svg width={sw} height={sh} style={{ marginTop: 10, overflow: "visible" }}>
        <line x1={0} y1={sh} x2={sw} y2={sh} stroke={C.line} strokeWidth={2} />
        <polyline points={pts} fill="none" stroke={C.teal} strokeWidth={3.5} strokeLinejoin="round" />
      </svg>
      <div style={{ fontFamily: FONT.sans, fontSize: 24, color: C.dim, marginTop: 18 }}>Degrees from sensor geometry, not from the AI</div>
    </div>
  );
};
