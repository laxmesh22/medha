import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";

const ease = Easing.bezier(0.16, 1, 0.3, 1);

/** Dark studio backdrop shared by the intro and outro: teal glow, drifting grid, a range-of-motion arc. */
export const Backdrop: React.FC<{ arcTo?: number }> = ({ arcTo = 134 }) => {
  const frame = useCurrentFrame();
  const sweep = interpolate(frame, [10, 80], [0, arcTo], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const r = 330;
  const cx = 1590;
  const cy = 560;
  const p = (d: number) => {
    const a = ((90 + d) * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const [x0, y0] = p(0);
  const [x1, y1] = p(sweep);
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <AbsoluteFill
        style={{
          backgroundImage:
            "linear-gradient(rgba(79,199,166,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(79,199,166,0.07) 1px, transparent 1px)",
          backgroundSize: "80px 80px",
          backgroundPosition: `${frame * 0.4}px ${frame * 0.25}px`,
          maskImage: "radial-gradient(ellipse at 70% 50%, black 10%, transparent 70%)",
        }}
      />
      <AbsoluteFill style={{ background: "radial-gradient(circle at 78% 52%, rgba(79,199,166,0.22), transparent 45%)" }} />
      <svg width={1920} height={1080} style={{ position: "absolute" }}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={2} />
        {sweep > 0.5 ? (
          <path
            d={`M ${x0} ${y0} A ${r} ${r} 0 ${sweep > 180 ? 1 : 0} 1 ${x1} ${y1}`}
            fill="none"
            stroke={C.teal}
            strokeWidth={6}
            strokeLinecap="round"
          />
        ) : null}
        <line x1={cx} y1={cy} x2={x1} y2={y1} stroke="rgba(79,199,166,0.5)" strokeWidth={3} />
        <circle cx={x1} cy={y1} r={14} fill={C.text} stroke={C.teal} strokeWidth={5} />
        <circle cx={cx} cy={cy} r={8} fill={C.teal} />
      </svg>
    </AbsoluteFill>
  );
};

export const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const t = (a: number, d = 20) =>
    interpolate(frame, [a, a + d], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const word = "Physio Buddy";
  return (
    <AbsoluteFill>
      <Backdrop />
      <div style={{ position: "absolute", left: 140, top: 330 }}>
        <div style={{ fontFamily: FONT.mono, fontSize: 28, letterSpacing: 8, color: C.teal, opacity: t(4), textTransform: "uppercase" }}>
          Frozen-shoulder rehab · prototype
        </div>
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 168, color: C.text, marginTop: 18, letterSpacing: -4, display: "flex" }}>
          {word.split("").map((ch, k) => (
            <span
              key={k}
              style={{
                display: "inline-block",
                whiteSpace: "pre",
                opacity: t(10 + k * 2, 16),
                translate: `0px ${(1 - t(10 + k * 2, 16)) * 60}px`,
              }}
            >
              {ch}
            </span>
          ))}
        </div>
        <div style={{ fontFamily: FONT.sans, fontSize: 48, color: C.dim, marginTop: 24, opacity: t(40), translate: `0px ${(1 - t(40)) * 24}px` }}>
          Wearable motion sensing that measures every rep
        </div>
      </div>
    </AbsoluteFill>
  );
};
