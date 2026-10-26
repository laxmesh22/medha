import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";

const ease = Easing.bezier(0.16, 1, 0.3, 1);

type Props = {
  anchor: [number, number]; // tracked point on the object (px)
  label: string;
  sub?: string;
  dx: number; // elbow offset from the anchor; the label runs horizontally away from the elbow
  dy: number;
  start: number; // frame (scene-local) when the callout starts drawing
  end?: number; // frame when it fades out
};

/** Leader-line callout: pulsing dot on the tracked point, a two-segment line, then a label panel. */
export const Callout: React.FC<Props> = ({ anchor, label, sub, dx, dy, start, end = 1e9 }) => {
  const frame = useCurrentFrame();
  const draw = interpolate(frame, [start, start + 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const out = interpolate(frame, [end - 10, end], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  if (draw <= 0 || out <= 0) return null;
  const [ax, ay] = anchor;
  const ex = ax + dx;
  const ey = ay + dy;
  const dir = dx >= 0 ? 1 : -1;
  const hx = ex + dir * 70;
  const seg1 = Math.hypot(dx, dy);
  const total = seg1 + 70;
  const textIn = interpolate(frame, [start + 10, start + 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
  const pulse = (frame - start) % 40;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: out }}>
      <svg width="1920" height="1080" style={{ position: "absolute", inset: 0 }}>
        <circle
          cx={ax}
          cy={ay}
          r={interpolate(pulse, [0, 40], [8, 30])}
          fill="none"
          stroke={C.teal}
          strokeWidth={2}
          opacity={interpolate(pulse, [0, 40], [0.7, 0]) * draw}
        />
        <circle cx={ax} cy={ay} r={7 * draw} fill={C.teal} stroke={C.bg} strokeWidth={2} />
        <polyline
          points={`${ax},${ay} ${ex},${ey} ${hx},${ey}`}
          fill="none"
          stroke={C.teal}
          strokeWidth={2.5}
          strokeDasharray={total}
          strokeDashoffset={total * (1 - draw)}
        />
      </svg>
      <div
        style={{
          position: "absolute",
          top: ey - 38,
          left: dir > 0 ? hx + 14 : undefined,
          right: dir < 0 ? 1920 - hx + 14 : undefined,
          opacity: textIn,
          translate: `${(1 - textIn) * 24 * dir}px 0px`,
          padding: "12px 20px 14px",
          background: C.panel,
          borderLeft: dir > 0 ? `4px solid ${C.teal}` : undefined,
          borderRight: dir < 0 ? `4px solid ${C.teal}` : undefined,
          textAlign: dir > 0 ? "left" : "right",
          backdropFilter: "blur(6px)",
          whiteSpace: "nowrap",
        }}
      >
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 36, color: C.text, lineHeight: 1.1 }}>{label}</div>
        {sub ? (
          <div style={{ fontFamily: FONT.mono, fontSize: 24, color: C.dim, marginTop: 6, letterSpacing: 0.5 }}>{sub}</div>
        ) : null}
      </div>
    </div>
  );
};
