import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { FONT } from "../theme";
import { A } from "./brand";

// The dashboard captures are 2x screenshots of a 1440 x 810 CSS viewport (video/scripts/capture_dashboard.mjs).
// Every position below is in those CSS pixels; the window shows the viewport at 1:1 on the 1920 x 1080 frame.
export const VIEW_W = 1440;
export const VIEW_H = 810;
const BAR = 38;
export const WIN_LEFT = (1920 - VIEW_W) / 2;
export const WIN_TOP = 1080 - VIEW_H - BAR - 36;

const ease = Easing.bezier(0.65, 0, 0.35, 1);

export type Shot = { src: string; h: number; from: number; url?: string };
export type CamKey = { f: number; x: number; y: number; z: number };
export type CursorKey = { f: number; x: number; y: number };
export type Box = { x: number; y: number; w: number; h: number; from: number; to: number };

/** Value of keyed numbers at a frame, eased between keys and held outside them. */
function keyed<K extends { f: number }>(keys: K[], frame: number, get: (k: K) => number[]): number[] {
  if (frame <= keys[0].f) return get(keys[0]);
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i], b = keys[i + 1];
    if (frame < b.f) {
      const t = ease((frame - a.f) / (b.f - a.f));
      const va = get(a), vb = get(b);
      return va.map((v, j) => v + (vb[j] - v) * t);
    }
  }
  return get(keys[keys.length - 1]);
}

/** Camera: focus point (CSS px) at the viewport centre with zoom, clamped so the page always fills the view. */
function camera(keys: CamKey[], frame: number, pageH: number) {
  const [x, y, z] = keyed(keys, frame, (k) => [k.x, k.y, k.z]);
  const left = Math.min(0, Math.max(VIEW_W - VIEW_W * z, VIEW_W / 2 - x * z));
  const top = Math.min(0, Math.max(VIEW_H - pageH * z, VIEW_H / 2 - y * z));
  return { left, top, z, map: (px: number, py: number) => [left + px * z, top + py * z] as const };
}

const Arrow: React.FC<{ scale: number }> = ({ scale }) => (
  <svg width={34} height={42} viewBox="0 0 17 26" style={{ transform: `scale(${scale})`, transformOrigin: "0 0", filter: "drop-shadow(0 3px 5px rgba(0,0,0,0.35))" }}>
    <path d="M1 1 L1 20 L6 15.5 L9.6 23.6 L12.6 22.3 L9.1 14.3 L15.4 14.3 Z" fill="#111" stroke="#fff" strokeWidth="1.3" strokeLinejoin="round" />
  </svg>
);

/** A browser window playing a walkthrough: crossfading screenshots, a moving camera, cursor clicks and highlights. */
export const Screen: React.FC<{
  shots: Shot[];
  cam: CamKey[];
  cursor?: CursorKey[];
  clicks?: number[];
  boxes?: Box[];
  cursorUntil?: number;
}> = ({ shots, cam, cursor = [], clicks = [], boxes = [], cursorUntil = 1e6 }) => {
  const frame = useCurrentFrame();
  const active = shots.filter((s) => s.from <= frame).pop() ?? shots[0];
  const c = camera(cam, frame, Math.max(...shots.filter((s) => s.from <= frame + 8).map((s) => s.h), VIEW_H));
  const url = active.url ?? "Auri · Clinician dashboard";

  let cur: React.ReactNode = null;
  if (cursor.length) {
    const [cx, cy] = keyed(cursor, frame, (k) => [k.x, k.y]);
    const [sx, sy] = c.map(cx, cy);
    const o = interpolate(frame, [cursor[0].f, cursor[0].f + 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
      * interpolate(frame, [cursorUntil - 6, cursorUntil], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    const press = clicks.reduce((m, f) => Math.max(m, interpolate(frame, [f - 3, f, f + 5], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })), 0);
    cur = (
      <>
        {clicks.map((f) => {
          const t = (frame - f) / 16;
          if (t < 0 || t > 1) return null;
          return <div key={f} style={{ position: "absolute", left: sx, top: sy, width: 90 * t, height: 90 * t, translate: "-50% -50%", borderRadius: "50%",
            border: `3px solid ${A.accent}`, opacity: 1 - t }} />;
        })}
        <div style={{ position: "absolute", left: sx - 2, top: sy - 2, opacity: o }}><Arrow scale={1 - 0.15 * press} /></div>
      </>
    );
  }

  return (
    <div style={{ position: "absolute", left: WIN_LEFT, top: WIN_TOP, width: VIEW_W, height: VIEW_H + BAR, borderRadius: 14, overflow: "hidden",
      background: "#fff", boxShadow: "0 40px 90px rgba(9, 40, 37, 0.28), 0 6px 18px rgba(9, 40, 37, 0.12)", border: "1px solid rgba(14,79,74,0.18)" }}>
      <div style={{ height: BAR, background: "#eceae3", display: "flex", alignItems: "center", gap: 8, padding: "0 16px", borderBottom: "1px solid #dcd9cf" }}>
        {["#e4605a", "#e7b53e", "#5fbf5a"].map((col) => <span key={col} style={{ width: 12, height: 12, borderRadius: 6, background: col }} />)}
        <div style={{ margin: "0 auto", padding: "4px 22px", borderRadius: 999, background: "#f8f7f2", fontFamily: FONT.sans, fontSize: 16, color: "#4a5a58", minWidth: 380, textAlign: "center" }}>
          {url}
        </div>
        <span style={{ width: 52 }} />
      </div>
      <div style={{ position: "relative", width: VIEW_W, height: VIEW_H, overflow: "hidden", background: "#f6f5f0" }}>
        {shots.map((s, i) => {
          const o = i === 0 ? 1 : interpolate(frame, [s.from, s.from + 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          if (o <= 0) return null;
          return <Img key={s.src} src={staticFile(`intro/${s.src}.png`)} style={{ position: "absolute", left: c.left, top: c.top, width: VIEW_W * c.z, height: s.h * c.z, opacity: o }} />;
        })}
        {boxes.map((b, i) => {
          const o = interpolate(frame, [b.from, b.from + 8, b.to - 8, b.to], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          if (o <= 0) return null;
          const [x, y] = c.map(b.x, b.y);
          const pad = 8;
          return <div key={i} style={{ position: "absolute", left: x - pad, top: y - pad, width: b.w * c.z + 2 * pad, height: b.h * c.z + 2 * pad, borderRadius: 14,
            border: `3px solid ${A.accent}`, boxShadow: `0 0 0 9999px rgba(8, 36, 33, ${0.28 * o}), 0 0 24px rgba(0,137,123,0.55)`, opacity: o }} />;
        })}
        {cur}
      </div>
      {clicks.map((f) => (
        <Sequence key={f} from={f - 1} durationInFrames={20}><Audio src={staticFile("audio/click.wav")} volume={0.55} /></Sequence>
      ))}
    </div>
  );
};

export type Cap = { from: number; kicker: string; title: string };

/** Kicker + headline above the window; a new caption slides in at its frame. */
export const Captions: React.FC<{ caps: Cap[]; step?: number }> = ({ caps, step }) => {
  const frame = useCurrentFrame();
  const cap = caps.filter((c) => c.from <= frame).pop() ?? caps[0];
  const t = interpolate(frame - cap.from, [0, 14], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.16, 1, 0.3, 1) });
  return (
    <AbsoluteFill>
      <div key={cap.from} style={{ position: "absolute", left: WIN_LEFT, top: 40, opacity: t, translate: `0 ${(1 - t) * 18}px` }}>
        <div style={{ fontFamily: FONT.mono, fontSize: 20, letterSpacing: 4, color: A.accent, textTransform: "uppercase" }}>{cap.kicker}</div>
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 50, color: A.ink, marginTop: 6, letterSpacing: -0.5 }}>{cap.title}</div>
      </div>
      {step !== undefined ? <Steps current={step} /> : null}
    </AbsoluteFill>
  );
};

const STEP_NAMES = ["Sign up", "Overview", "Patients", "Progress", "Care plan", "Video"];

const Steps: React.FC<{ current: number }> = ({ current }) => (
  <div style={{ position: "absolute", right: WIN_LEFT, top: 26, display: "flex", gap: 8 }}>
    {STEP_NAMES.map((s, i) => (
      <span key={s} style={{ fontFamily: FONT.sans, fontSize: 18, fontWeight: 600, padding: "6px 14px", borderRadius: 999,
        background: i === current ? A.brand : "transparent", color: i === current ? "#fff" : i < current ? A.brand : "#8a9a97",
        border: `1.5px solid ${i <= current ? A.brand : "#cfd6d3"}` }}>
        {s}
      </span>
    ))}
  </div>
);

/** Off-white stage behind the window with a faint teal grid. */
export const Stage: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ background: A.paper }}>
    <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(14,79,74,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(14,79,74,0.05) 1px, transparent 1px)",
      backgroundSize: "48px 48px" }} />
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 110%, rgba(0,137,123,0.16), rgba(0,0,0,0) 60%)" }} />
    {children}
  </AbsoluteFill>
);
