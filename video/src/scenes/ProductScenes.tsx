import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Callout } from "../components/Callout";
import { Footage } from "../components/Footage";
import { SceneTitle } from "../components/SceneTitle";
import { RAIL_CLICK } from "../timeline";
import { C, FONT } from "../theme";
import { point } from "../track";

// callouts appear while the pod is exploded (device_film.py: explode 10-37 %, reassemble from 72 %)
const EXPLODED = [52, 96] as const;

export const Product: React.FC = () => {
  const frame = useCurrentFrame();
  const parts: { key: string; label: string; sub: string; dx: number; dy: number; at: number }[] = [
    { key: "lid", label: "Snap-fit lid", sub: "arrow shows wear direction", dx: -170, dy: -60, at: 0 },
    { key: "lipo", label: "500 mAh LiPo", sub: "USB-C charging", dx: -210, dy: 40, at: 4 },
    { key: "drv2605", label: "DRV2605L haptics", sub: "haptic cue on the arm", dx: 190, dy: -70, at: 8 },
    { key: "xiao", label: "XIAO ESP32-S3", sub: "wireless to the station", dx: 220, dy: 70, at: 12 },
    { key: "bno085", label: "BNO085 IMU", sub: "9-axis orientation", dx: -230, dy: 130, at: 16 },
  ];
  return (
    <Footage
      shot="product"
      push={0.02}
      overlay={(map) => (
        <AbsoluteFill>
          {parts.map((p) => (
            <Callout
              key={p.key}
              anchor={map(point("product", p.key, frame))}
              label={p.label}
              sub={p.sub}
              dx={p.dx}
              dy={p.dy}
              start={EXPLODED[0] + p.at}
              end={EXPLODED[1] + p.at / 2}
            />
          ))}
          <SceneTitle kicker="Upper-arm pod" title="Everything in 61 × 31 mm" sub="3D-printed PETG, real component models" />
        </AbsoluteFill>
      )}
    />
  );
};

export const Rail: React.FC = () => {
  const frame = useCurrentFrame();
  const since = frame - RAIL_CLICK;
  return (
    <Footage
      shot="rail"
      push={0.03}
      overlay={(map) => {
        const [x, y] = map(point("rail", "pod", frame));
        return (
          <AbsoluteFill>
            {since >= 0 && since < 30 ? (
              <svg width={1920} height={1080} style={{ position: "absolute" }}>
                {[0, 7].map((d) => (
                  <circle
                    key={d}
                    cx={x}
                    cy={y}
                    r={interpolate(since - d, [0, 22], [30, 260], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}
                    fill="none"
                    stroke={C.teal}
                    strokeWidth={4}
                    opacity={interpolate(since - d, [0, 22], [0.9, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}
                  />
                ))}
              </svg>
            ) : null}
            {since >= 0 ? (
              <div
                style={{
                  position: "absolute",
                  left: x - 70,
                  top: y - 190,
                  width: 140,
                  textAlign: "center",
                  fontFamily: FONT.mono,
                  fontWeight: 700,
                  fontSize: 34,
                  letterSpacing: 6,
                  color: C.teal,
                  opacity: interpolate(since, [0, 4, 26, 34], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
                  scale: interpolate(since, [0, 6], [1.4, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
                }}
              >
                CLICK
              </div>
            ) : null}
            <SceneTitle kicker="PB-rail quick release" title="Slides on. Clicks in." sub="Same place, same angle, every session" />
          </AbsoluteFill>
        );
      }}
    />
  );
};

export const Family: React.FC = () => {
  const frame = useCurrentFrame();
  const units = [
    { key: "forearm", label: "Forearm", sub: "IMU only" },
    { key: "upperarm", label: "Upper arm", sub: "IMU + haptics" },
    { key: "waist", label: "Waist", sub: "body reference" },
  ];
  return (
    <Footage
      shot="family"
      push={0.025}
      overlay={(map) => (
        <AbsoluteFill>
          {units.map((u, k) => {
            const [x, y] = map(point("family", u.key, frame));
            const t = interpolate(frame, [8 + k * 6, 24 + k * 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
            return (
              <div
                key={u.key}
                style={{
                  position: "absolute",
                  left: x - 160,
                  top: y - 170,
                  width: 320,
                  textAlign: "center",
                  opacity: t,
                  translate: `0px ${(1 - t) * 20}px`,
                }}
              >
                <div style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 44, color: C.text }}>{u.label}</div>
                <div style={{ fontFamily: FONT.mono, fontSize: 24, color: C.teal, marginTop: 4 }}>{u.sub}</div>
                <div style={{ width: 2, height: 46 * t, background: C.teal, margin: "10px auto 0" }} />
              </div>
            );
          })}
          <SceneTitle kicker="One rail, three units" title="Same base, any pod" />
        </AbsoluteFill>
      )}
    />
  );
};
