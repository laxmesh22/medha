import React from "react";
import { Audio } from "@remotion/media";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { AbsoluteFill, Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT } from "../theme";
import { A } from "./brand";
import { Box, Captions, Screen, Stage } from "./Screen";

// Intro video of the Auri clinician dashboard: 1920 x 1080, 30 fps, about 54 s. Screens come from
// video/scripts/capture_dashboard.mjs (demo data, fictional patients); music from make_soundtrack.py --intro.
export const INTRO_FADE = 12;

const out = Easing.bezier(0.16, 1, 0.3, 1);
const rise = (frame: number, at: number, len = 18) => interpolate(frame, [at, at + len], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: out });

const Mark: React.FC<{ size: number }> = ({ size }) => (
  <span style={{ width: size, height: size, borderRadius: size * 0.24, background: A.paper, display: "inline-flex", alignItems: "center", justifyContent: "center", color: A.brand }}>
    <svg width={size * 0.6} height={size * 0.6} viewBox="0 0 32 32"><path d="M7 23 L15 9 L25 23" stroke="currentColor" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
  </span>
);

const TealBg: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ background: `radial-gradient(ellipse at 75% 40%, #146a62 0%, ${A.brand} 45%, ${A.brandDeep} 100%)` }}>
    <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
      backgroundSize: "48px 48px" }} />
    {children}
  </AbsoluteFill>
);

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 14 } });
  const img = rise(frame, 14, 30);
  return (
    <TealBg>
      <div style={{ position: "absolute", left: 160, top: 300 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 34, transform: `scale(${0.85 + 0.15 * pop})`, transformOrigin: "left center", opacity: pop }}>
          <Mark size={140} />
          <span style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 190, color: "#fff", letterSpacing: -4, lineHeight: 1 }}>Auri</span>
        </div>
        <div style={{ fontFamily: FONT.mono, fontSize: 30, letterSpacing: 8, color: A.mint, marginTop: 40, opacity: rise(frame, 18), translate: `0 ${(1 - rise(frame, 18)) * 20}px` }}>
          CLINICIAN DASHBOARD
        </div>
        <div style={{ fontFamily: FONT.sans, fontSize: 46, color: "#fff", marginTop: 26, maxWidth: 820, lineHeight: 1.2, opacity: rise(frame, 30), translate: `0 ${(1 - rise(frame, 30)) * 20}px` }}>
          Your patients' shoulder rehab, measured between visits.
        </div>
      </div>
      <div style={{ position: "absolute", right: 170, top: 190, width: 700, height: 700, borderRadius: "50%", overflow: "hidden", opacity: img,
        transform: `scale(${0.92 + 0.08 * img})`, border: `6px solid ${A.mint}`, boxShadow: "0 40px 100px rgba(0,0,0,0.35)" }}>
        <Img src={staticFile("intro/hero-raise.webp")} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${1.04 + frame * 0.0006})` }} />
      </div>
    </TealBg>
  );
};

const Premise: React.FC = () => {
  const frame = useCurrentFrame();
  const chips = ["Range of motion", "Adherence", "Pain", "Form flags"];
  return (
    <Stage>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 18 }}>
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 92, color: A.ink, letterSpacing: -1.5, opacity: rise(frame, 4), translate: `0 ${(1 - rise(frame, 4)) * 24}px` }}>
          Rehab happens at home.
        </div>
        <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 92, color: A.accent, letterSpacing: -1.5, opacity: rise(frame, 26), translate: `0 ${(1 - rise(frame, 26)) * 24}px` }}>
          Auri measures every rep.
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 40 }}>
          {chips.map((c, i) => (
            <span key={c} style={{ fontFamily: FONT.sans, fontSize: 30, fontWeight: 600, color: A.brand, padding: "10px 26px", borderRadius: 999,
              border: `2px solid ${A.brand}`, background: "#fff", opacity: rise(frame, 46 + i * 6), translate: `0 ${(1 - rise(frame, 46 + i * 6)) * 16}px` }}>
              {c}
            </span>
          ))}
        </div>
      </AbsoluteFill>
    </Stage>
  );
};

// CSS-pixel rectangles of the controls, from video/public/intro/rects.json and the captures
const R = {
  lgCreate: { x: 879, y: 562, w: 420, h: 42 },
  suGoogle: { x: 869, y: 430, w: 440, h: 42 },
  suContinue: { x: 1273, y: 705, w: 96, h: 42 },
  suCreate: { x: 1148, y: 635, w: 161, h: 42 },
  doneCode: { x: 869, y: 288, w: 398, h: 176 },
  ovAttention: { x: 281, y: 324, w: 738, h: 282 },
  ovCalls: { x: 1040, y: 324, w: 367, h: 208 },
  ptMeera: { x: 281, y: 438, w: 1127, h: 68 },
  prFlexion: { x: 281, y: 531, w: 553, h: 277 },
  planEdit: { x: 1291, y: 333, w: 94, h: 42 },
  planReps: { x: 586, y: 434, w: 63, h: 42 },
  planV2Row: { x: 281, y: 432, w: 1127, h: 48 },
  planV2Title: { x: 296, y: 330, w: 200, h: 28 },
  vidJoinLink: { x: 303, y: 503, w: 700, h: 42 },
  vidStart: { x: 303, y: 422, w: 159, h: 42 },
};
const mid = (r: { x: number; y: number; w: number; h: number }) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });
const box = (r: { x: number; y: number; w: number; h: number }, from: number, to: number): Box => ({ ...r, from, to });
const home = { x: 720, y: 405, z: 1 };

const Signup: React.FC = () => (
  <Stage>
    <Captions step={0} caps={[
      { from: 0, kicker: "For physiotherapists", title: "Create a doctor account" },
      { from: 110, kicker: "Sign up with Google", title: "Add your qualification, clinic and registration" },
      { from: 266, kicker: "Ready in two minutes", title: "Every doctor gets a referral code for patients" },
    ]} />
    <Screen
      shots={[
        { src: "login", h: 810, from: 0 },
        { src: "signup_account", h: 810, from: 60 },
        { src: "signup_details", h: 900, from: 110 },
        { src: "signup_confirm", h: 810, from: 220 },
        { src: "signup_done", h: 810, from: 266 },
      ]}
      cam={[{ f: 0, ...home }, { f: 115, ...home }, { f: 150, x: 1089, y: 430, z: 1.15 }, { f: 185, x: 1089, y: 430, z: 1.15 }, { f: 205, ...home },
        { f: 280, ...home }, { f: 310, x: 1068, y: 376, z: 1.35 }]}
      cursor={[{ f: 8, x: 1200, y: 740 }, { f: 45, ...mid(R.lgCreate) }, { f: 70, ...mid(R.lgCreate) }, { f: 95, ...mid(R.suGoogle) },
        { f: 180, x: 1200, y: 620 }, { f: 205, ...mid(R.suContinue) }, { f: 225, ...mid(R.suContinue) }, { f: 250, ...mid(R.suCreate) },
        { f: 275, x: 1400, y: 760 }]}
      clicks={[52, 102, 212, 258]}
      boxes={[box(R.doneCode, 288, 330)]}
    />
  </Stage>
);

const Overview: React.FC = () => (
  <Stage>
    <Captions step={1} caps={[
      { from: 0, kicker: "Overview", title: "Who needs you today, at a glance" },
      { from: 70, kicker: "Needs attention", title: "Pain alerts first, then missed sessions and form issues" },
      { from: 148, kicker: "Video calls", title: "Consults booked with your patients" },
    ]} />
    <Screen
      shots={[{ src: "overview", h: 1250, from: 0 }]}
      cam={[{ f: 0, ...home }, { f: 25, ...home }, { f: 70, x: 650, y: 465, z: 1.3 }, { f: 140, x: 650, y: 465, z: 1.3 }, { f: 168, x: 1150, y: 440, z: 1.3 }]}
      boxes={[box(R.ovAttention, 80, 145), box(R.ovCalls, 168, 210)]}
    />
  </Stage>
);

const Patients: React.FC = () => (
  <Stage>
    <Captions step={2} caps={[{ from: 0, kicker: "Patients", title: "Everyone who linked with your code" }]} />
    <Screen
      shots={[{ src: "patients", h: 810, from: 0 }]}
      cam={[{ f: 0, ...home }, { f: 105, x: 720, y: 430, z: 1.05 }]}
      cursor={[{ f: 10, x: 1150, y: 760 }, { f: 55, x: 400, y: 472 }]}
      clicks={[70]}
      boxes={[box(R.ptMeera, 45, 105)]}
    />
  </Stage>
);

const Progress: React.FC = () => (
  <Stage>
    <Captions step={3} caps={[
      { from: 0, kicker: "Patient progress", title: "Adherence, pain and form for each patient" },
      { from: 70, kicker: "Range of motion", title: "Measured by the sensors, never typed in" },
      { from: 190, kicker: "Sessions and pain", title: "Every home session, day by day" },
    ]} />
    <Screen
      shots={[{ src: "progress", h: 1640, from: 0 }]}
      cam={[{ f: 0, ...home }, { f: 35, ...home }, { f: 75, x: 720, y: 760, z: 1 }, { f: 105, x: 560, y: 600, z: 1.45 }, { f: 165, x: 560, y: 600, z: 1.45 },
        { f: 205, x: 720, y: 1240, z: 1 }]}
      boxes={[box(R.prFlexion, 110, 168)]}
    />
  </Stage>
);

const Plan: React.FC = () => (
  <Stage>
    <Captions step={4} caps={[
      { from: 0, kicker: "Care plan", title: "You prescribe the exercises, reps and targets" },
      { from: 70, kicker: "Edit the plan", title: "Targets and progression stay your call" },
      { from: 170, kicker: "Published as version 2", title: "Every change is versioned; older plans are kept" },
    ]} />
    <Screen
      shots={[{ src: "plan", h: 810, from: 0 }, { src: "plan_edit", h: 810, from: 66 }, { src: "plan_v2", h: 810, from: 170 }]}
      cam={[{ f: 0, ...home }, { f: 75, ...home }, { f: 105, x: 760, y: 470, z: 1.25 }, { f: 158, x: 760, y: 470, z: 1.25 }, { f: 172, ...home }]}
      cursor={[{ f: 8, x: 1000, y: 700 }, { f: 45, ...mid(R.planEdit) }, { f: 70, ...mid(R.planEdit) }, { f: 100, ...mid(R.planReps) },
        { f: 160, ...mid(R.planReps) }, { f: 195, x: 1100, y: 640 }]}
      clicks={[56, 108]}
      boxes={[box(R.planReps, 112, 162), box(R.planV2Title, 178, 240), box(R.planV2Row, 178, 240)]}
    />
  </Stage>
);

const Video: React.FC = () => (
  <Stage>
    <Captions step={5} caps={[
      { from: 0, kicker: "Video consults", title: "Book a call or start one from the patient's page" },
      { from: 140, kicker: "Camera check, then you're in", title: "Calls open in a secure Jitsi Meet room" },
    ]} />
    <Screen
      shots={[{ src: "video", h: 1000, from: 0 }, { src: "jitsi", h: 810, from: 136, url: "meet.jit.si · Auri consult" }]}
      cam={[{ f: 0, ...home }, { f: 20, ...home }, { f: 55, x: 640, y: 470, z: 1.25 }, { f: 128, x: 640, y: 470, z: 1.25 }, { f: 138, ...home }]}
      cursor={[{ f: 10, x: 1000, y: 760 }, { f: 100, ...mid(R.vidStart) }]}
      clicks={[118]}
      cursorUntil={136}
      boxes={[box(R.vidJoinLink, 50, 98), box(R.vidStart, 98, 132)]}
    />
  </Stage>
);

const FEATURES = [
  "Google sign-in and doctor sign-up",
  "Patients link with your referral code",
  "Range of motion measured by the sensors",
  "Versioned care plans you control",
  "Video consults with each patient",
];

const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 14 } });
  return (
    <TealBg>
      <div style={{ position: "absolute", left: 160, top: 400, display: "flex", alignItems: "center", gap: 28, opacity: pop, transform: `scale(${0.88 + 0.12 * pop})`, transformOrigin: "left center" }}>
        <Mark size={110} />
        <div>
          <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 140, color: "#fff", letterSpacing: -3, lineHeight: 1 }}>Auri</div>
          <div style={{ fontFamily: FONT.mono, fontSize: 26, letterSpacing: 7, color: A.mint, marginTop: 10 }}>CLINICIAN DASHBOARD</div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 1000, top: 345, display: "flex", flexDirection: "column", gap: 26 }}>
        {FEATURES.map((f, i) => {
          const t = rise(frame, 14 + i * 7);
          return (
            <div key={f} style={{ display: "flex", alignItems: "center", gap: 20, opacity: t, translate: `${(1 - t) * 30}px 0` }}>
              <span style={{ width: 40, height: 40, borderRadius: 20, background: A.accent, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="22" height="22" viewBox="0 0 24 24"><path d="M5 12.5 L10 17 L19 7" stroke="#fff" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </span>
              <span style={{ fontFamily: FONT.sans, fontSize: 38, color: "#fff" }}>{f}</span>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 160, right: 160, bottom: 90, display: "flex", justifyContent: "space-between", fontFamily: FONT.sans, fontSize: 24,
        color: A.mint, opacity: rise(frame, 60) }}>
        <span>Shoulder rehab, measured between visits</span>
        <span>Demo data · fictional patients</span>
      </div>
    </TealBg>
  );
};

export const INTRO_SCENES: { id: string; duration: number; C: React.FC }[] = [
  { id: "title", duration: 120, C: Title },
  { id: "premise", duration: 105, C: Premise },
  { id: "signup", duration: 330, C: Signup },
  { id: "overview", duration: 210, C: Overview },
  { id: "patients", duration: 105, C: Patients },
  { id: "progress", duration: 240, C: Progress },
  { id: "plan", duration: 240, C: Plan },
  { id: "video", duration: 210, C: Video },
  { id: "outro", duration: 165, C: Outro },
];

export const INTRO_TOTAL = INTRO_SCENES.reduce((t, s) => t + s.duration, 0) - INTRO_FADE * (INTRO_SCENES.length - 1);

export const AuriIntro: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: A.paper }}>
      <TransitionSeries>
        {INTRO_SCENES.flatMap((s, i) => {
          const items = [
            <TransitionSeries.Sequence key={s.id} durationInFrames={s.duration}>
              <s.C />
            </TransitionSeries.Sequence>,
          ];
          if (i < INTRO_SCENES.length - 1) {
            items.push(<TransitionSeries.Transition key={`${s.id}-t`} presentation={fade()} timing={linearTiming({ durationInFrames: INTRO_FADE })} />);
          }
          return items;
        })}
      </TransitionSeries>
      <Audio src={staticFile("audio/intro_bgm.wav")} volume={(f) => interpolate(f, [0, 10, INTRO_TOTAL - 45, INTRO_TOTAL], [0, 0.85, 0.85, 0], { extrapolateRight: "clamp" })} />
    </AbsoluteFill>
  );
};
