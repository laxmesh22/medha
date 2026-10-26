import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "../theme";
import { Backdrop } from "./Intro";

const ease = Easing.bezier(0.16, 1, 0.3, 1);

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = (a: number, d = 18) =>
    interpolate(frame, [a, a + d], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const fade = interpolate(frame, [durationInFrames - 24, durationInFrames - 2], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const lines = ["Angles from sensor geometry", "Form checked by the AI coach", "Targets set by your clinician"];
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <Backdrop arcTo={180} />
      <div style={{ position: "absolute", left: 140, top: 240 }}>
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 120, color: C.text, letterSpacing: -3, opacity: t(4) }}>Physio Buddy</div>
        <div style={{ marginTop: 40 }}>
          {lines.map((l, k) => (
            <div
              key={l}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 24,
                fontFamily: FONT.sans,
                fontSize: 50,
                color: C.text,
                marginTop: 18,
                opacity: t(18 + k * 10),
                translate: `${(1 - t(18 + k * 10)) * -30}px 0px`,
              }}
            >
              <span style={{ width: 18, height: 18, borderRadius: 9, background: C.teal }} />
              {l}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 70, fontFamily: FONT.mono, fontSize: 30, color: C.dim, opacity: t(56), letterSpacing: 1 }}>
          Clinic station: Jetson Orin Nano + RealSense D455f
        </div>
        <div style={{ marginTop: 14, fontFamily: FONT.mono, fontSize: 30, color: C.teal, opacity: t(64), letterSpacing: 4 }}>
          IIT BOMBAY · 31 OCTOBER 2026
        </div>
      </div>
    </AbsoluteFill>
  );
};
