import React from "react";
import { Audio, Video } from "@remotion/media";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Callout } from "../components/Callout";
import { Backdrop } from "../scenes/Intro";
import { C, FONT } from "../theme";
import { guidePoint } from "./gtrack";
import { Progress, StepPanel } from "./StepPanel";
import { BUILD_STEPS, GUIDE_FADE, GUIDE_START, GUIDE_TOTAL, Step, stepFrames, STEPS } from "./steps";
import { WiringDiagram } from "./WiringDiagram";

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const PANEL_LEFT = 1230; // StepPanel: right 70 + width 600 on a 1920 frame, minus a margin

const footageSrc = (s: Step) => staticFile(s.source === "film" ? `footage/${s.clip}.mp4` : `guide/footage/${s.clip}.mp4`);

const ClipStep: React.FC<{ step: Step }> = ({ step }) => {
  const frame = useCurrentFrame();
  const n = step.clipFrames!;
  const f = Math.min(frame, n - 1);
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <Sequence durationInFrames={n} layout="absolute-fill">
        <Video src={footageSrc(step)} muted style={{ width: "100%", height: "100%" }} />
      </Sequence>
      <Sequence from={n} layout="absolute-fill">
        <Img src={staticFile(`guide/stills/${step.clip}.png`)} style={{ width: "100%", height: "100%" }} />
      </Sequence>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 35% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.5) 100%)" }} />
      {(step.tags ?? []).map((tg, k) => {
        const p = guidePoint(step.clip!, tg.key, f, step.source);
        const o = interpolate(frame, [30 + k * 4, 40 + k * 4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        return (
          <div key={tg.key} style={{ position: "absolute", left: p[0], top: p[1], translate: `-50% ${-44 - (1 - o) * 10}px`, opacity: o,
            fontFamily: FONT.sans, fontWeight: 700, fontSize: 22, color: C.text, padding: "4px 12px", borderRadius: 999,
            background: "rgba(7,10,13,0.82)", border: `1px solid ${C.teal}`, whiteSpace: "nowrap" }}>
            {tg.label}
          </div>
        );
      })}
      {(step.callouts ?? []).map((c) => {
        const p = guidePoint(step.clip!, c.key, f, step.source);
        // keep the label in the free area (left of the step panel, inside the frame): flip sides if it would not fit
        const labelW = Math.max(c.label.length * 21, (c.sub ?? "").length * 15) + 110;
        let dx = c.dx;
        if (dx > 0 && p[0] + dx + labelW > PANEL_LEFT) dx = -Math.abs(dx);
        else if (dx < 0 && p[0] + dx - labelW < 30) dx = Math.abs(dx);
        return <Callout key={c.key + c.start} anchor={[p[0], p[1]]} label={c.label} sub={c.sub} dx={dx} dy={c.dy} start={c.start} end={c.end} />;
      })}
    </AbsoluteFill>
  );
};

const WiringStep: React.FC<{ step: Step }> = ({ step }) => (
  <AbsoluteFill>
    <Backdrop arcTo={0} />
    <div style={{ position: "absolute", left: 60, top: 56, fontFamily: FONT.mono, fontSize: 24, letterSpacing: 5, color: C.teal }}>
      {step.kind === "wiring" ? "UPPER-ARM UNIT · ONE I2C BUS" : "WAIST UNIT · ONE I2C BUS"}
    </div>
    <div style={{ position: "absolute", left: 0, top: 0, width: 1240, height: 1080, scale: 0.92, transformOrigin: "0 0" }}>
      <WiringDiagram variant={step.kind === "wiring" ? "arm" : "waist"} />
    </div>
  </AbsoluteFill>
);

const CardStep: React.FC<{ step: Step }> = ({ step }) => {
  const frame = useCurrentFrame();
  const t = (a: number, d = 18) =>
    interpolate(frame, [a, a + d], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  return (
    <AbsoluteFill>
      <Backdrop arcTo={step.id === "done" ? 180 : 134} />
      <div style={{ position: "absolute", left: 140, top: step.warn ? 180 : 250, width: 1150 }}>
        <div style={{ fontFamily: FONT.mono, fontSize: 28, letterSpacing: 8, color: C.teal, textTransform: "uppercase", opacity: t(4) }}>
          {step.id === "title" ? "Physio Buddy · assembly guide" : step.section}
        </div>
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: step.id === "title" ? 124 : 96, color: C.text, lineHeight: 1.02, marginTop: 18, opacity: t(10), translate: `0px ${(1 - t(10)) * 30}px` }}>
          {step.title}
        </div>
        <div style={{ marginTop: 40 }}>
          {step.bullets.map((b, k) => (
            <div key={b} style={{ display: "flex", alignItems: "flex-start", gap: 22, fontFamily: FONT.sans, fontSize: 42, lineHeight: 1.25, color: C.text, marginTop: 16, opacity: t(24 + k * 8), translate: `${(1 - t(24 + k * 8)) * -24}px 0px` }}>
              <span style={{ flex: "0 0 auto", width: 18, height: 18, borderRadius: 9, background: C.teal, marginTop: 18 }} />
              {b}
            </div>
          ))}
        </div>
        {step.warn ? (
          <div style={{ marginTop: 40, padding: "20px 26px", borderLeft: `6px solid ${C.amber}`, background: "rgba(242, 184, 75, 0.10)", fontFamily: FONT.sans, fontSize: 36, color: "#f7d796", opacity: t(60) }}>
            {step.warn}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const GuideStep: React.FC<{ step: Step }> = ({ step }) => {
  const frame = useCurrentFrame();
  const index = BUILD_STEPS.findIndex((s) => s.id === step.id) + 1;
  return (
    <AbsoluteFill>
      {step.kind === "clip" ? <ClipStep step={step} /> : step.kind === "card" ? <CardStep step={step} /> : <WiringStep step={step} />}
      {step.kind !== "card" ? <StepPanel step={step} index={index} total={BUILD_STEPS.length} /> : null}
      {step.kind !== "card" ? <Progress index={index} total={BUILD_STEPS.length} local={frame} length={stepFrames(step)} /> : null}
    </AbsoluteFill>
  );
};

// clicks where something latches: lid snaps, rail latch, power switch (frames within each step)
const CLICKS: [string, number][] = [
  ["lid", 48],
  ["forearm", 103],
  ["rail", 59],
  ["power", 20],
];

export const Guide: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    <TransitionSeries>
      {STEPS.flatMap((s, i) => {
        const seq = (
          <TransitionSeries.Sequence key={s.id} name={s.id} durationInFrames={stepFrames(s)}>
            <GuideStep step={s} />
          </TransitionSeries.Sequence>
        );
        return i < STEPS.length - 1
          ? [seq, <TransitionSeries.Transition key={`${s.id}-x`} presentation={fade()} timing={linearTiming({ durationInFrames: GUIDE_FADE })} />]
          : [seq];
      })}
    </TransitionSeries>
    <Audio
      src={staticFile("audio/guide_bgm.wav")}
      volume={(f) => interpolate(f, [0, 15, GUIDE_TOTAL - 30, GUIDE_TOTAL], [0, 0.55, 0.55, 0], { extrapolateRight: "clamp" })}
    />
    {STEPS.slice(1).map((s) => (
      <Sequence key={`c-${s.id}`} from={GUIDE_START[s.id] + 4} durationInFrames={36} layout="none">
        <Audio src={staticFile("audio/chime.wav")} volume={0.4} />
      </Sequence>
    ))}
    {CLICKS.map(([id, f]) => (
      <Sequence key={`k-${id}`} from={GUIDE_START[id] + f} durationInFrames={10} layout="none">
        <Audio src={staticFile("audio/click.wav")} volume={0.8} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
