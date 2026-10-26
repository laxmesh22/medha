import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Step } from "./steps";

const ease = Easing.bezier(0.16, 1, 0.3, 1);

/** Right-hand instruction panel: step number, title, bullets, parts chips, warning. */
export const StepPanel: React.FC<{ step: Step; index: number; total: number; width?: number }> = ({ step, index, total, width = 600 }) => {
  const frame = useCurrentFrame();
  const t = (a: number, d = 16) =>
    interpolate(frame, [a, a + d], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  return (
    <div
      style={{
        position: "absolute",
        right: 70,
        top: 90,
        bottom: 120,
        width,
        padding: "44px 46px",
        background: "rgba(7, 10, 13, 0.80)",
        border: `1px solid ${C.line}`,
        borderRadius: 20,
        backdropFilter: "blur(12px)",
        display: "flex",
        flexDirection: "column",
        opacity: t(0, 12),
        translate: `${(1 - t(0, 14)) * 40}px 0px`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: FONT.mono, fontSize: 24, letterSpacing: 4, color: C.teal }}>
        <span style={{ textTransform: "uppercase" }}>{step.section}</span>
        {index > 0 ? (
          <span style={{ color: C.dim }}>
            {String(index).padStart(2, "0")} / {String(total).padStart(2, "0")}
          </span>
        ) : null}
      </div>
      <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 58, color: C.text, lineHeight: 1.05, marginTop: 18, opacity: t(4) }}>
        {step.title}
      </div>
      <div style={{ marginTop: 26 }}>
        {step.bullets.map((b, k) => (
          <div
            key={b}
            style={{
              display: "flex",
              gap: 18,
              fontFamily: FONT.sans,
              fontSize: 31,
              lineHeight: 1.28,
              color: C.text,
              marginTop: 16,
              opacity: t(10 + k * 7),
              translate: `0px ${(1 - t(10 + k * 7)) * 14}px`,
            }}
          >
            <span
              style={{
                flex: "0 0 auto",
                width: 34,
                height: 34,
                marginTop: 3,
                borderRadius: 17,
                border: `2px solid ${C.teal}`,
                color: C.teal,
                fontFamily: FONT.mono,
                fontSize: 20,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {k + 1}
            </span>
            <span>{b}</span>
          </div>
        ))}
      </div>
      {step.need ? (
        <div style={{ marginTop: "auto", paddingTop: 22, opacity: t(30) }}>
          <div style={{ fontFamily: FONT.mono, fontSize: 20, letterSpacing: 3, color: C.dim, marginBottom: 10 }}>YOU NEED</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {step.need.map((n) => (
              <span
                key={n}
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 22,
                  color: C.text,
                  padding: "6px 14px",
                  borderRadius: 999,
                  border: `1px solid ${C.line}`,
                  background: "rgba(255,255,255,0.04)",
                }}
              >
                {n}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {step.warn ? (
        <div
          style={{
            marginTop: step.need ? 22 : "auto",
            padding: "16px 20px",
            borderLeft: `5px solid ${C.amber}`,
            background: "rgba(242, 184, 75, 0.10)",
            fontFamily: FONT.sans,
            fontSize: 27,
            lineHeight: 1.3,
            color: "#f7d796",
            opacity: t(36),
          }}
        >
          {step.warn}
        </div>
      ) : null}
    </div>
  );
};

/** Thin progress bar along the bottom with one tick per build step. */
export const Progress: React.FC<{ index: number; total: number; local: number; length: number }> = ({ index, total, local, length }) => {
  const done = Math.max(0, index - 1 + Math.min(1, local / Math.max(1, length)));
  return (
    <div style={{ position: "absolute", left: 120, right: 120, bottom: 54, height: 6, background: "rgba(255,255,255,0.10)", borderRadius: 3 }}>
      <div style={{ width: `${(done / total) * 100}%`, height: "100%", background: C.teal, borderRadius: 3 }} />
      {Array.from({ length: total - 1 }, (_, k) => (
        <div key={k} style={{ position: "absolute", left: `${((k + 1) / total) * 100}%`, top: -3, width: 2, height: 12, background: "rgba(255,255,255,0.25)" }} />
      ))}
    </div>
  );
};
