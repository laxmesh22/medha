import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "../theme";

const ease = Easing.bezier(0.16, 1, 0.3, 1);

/** Lower-third: teal kicker, headline and one supporting line, bottom-left inside the safe area. */
export const SceneTitle: React.FC<{ kicker: string; title: string; sub?: string; delay?: number; end?: number; align?: "left" | "right" }> = ({
  kicker,
  title,
  sub,
  delay = 8,
  end,
  align = "left",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = (a: number) =>
    interpolate(frame, [delay + a, delay + a + 18], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const stop = end ?? durationInFrames - 8;
  const out = interpolate(frame, [stop - 14, stop], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const side = align === "left" ? { left: 120 } : { right: 120 };
  return (
    <div style={{ position: "absolute", bottom: 110, ...side, opacity: out, textAlign: align, maxWidth: 1100 }}>
      <div
        style={{
          height: 4,
          width: 96 * t(0),
          background: C.teal,
          marginBottom: 22,
          marginLeft: align === "right" ? "auto" : 0,
        }}
      />
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 26,
          letterSpacing: 6,
          color: C.teal,
          textTransform: "uppercase",
          opacity: t(2),
          translate: `0px ${(1 - t(2)) * 16}px`,
        }}
      >
        {kicker}
      </div>
      <div
        style={{
          fontFamily: FONT.sans,
          fontWeight: 700,
          fontSize: 84,
          color: C.text,
          lineHeight: 1.04,
          marginTop: 10,
          opacity: t(5),
          translate: `0px ${(1 - t(5)) * 28}px`,
          textShadow: "0 4px 30px rgba(0,0,0,0.55)",
        }}
      >
        {title}
      </div>
      {sub ? (
        <div
          style={{
            fontFamily: FONT.sans,
            fontSize: 40,
            color: C.dim,
            marginTop: 16,
            opacity: t(10),
            translate: `0px ${(1 - t(10)) * 20}px`,
            textShadow: "0 2px 18px rgba(0,0,0,0.6)",
          }}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
};
