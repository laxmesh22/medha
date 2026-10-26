import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { HEIGHT, WIDTH } from "../timeline";

export type MapPoint = (p: readonly [number, number, ...unknown[]]) => [number, number];

/** A Blender shot (video/public/footage/<shot>.mp4) with a slow push-in and a vignette. `overlay` receives a function
 * that maps tracked footage pixels through the same push-in, so callouts stay pinned to the object. */
export const Footage: React.FC<{ shot: string; push?: number; overlay?: (map: MapPoint) => React.ReactNode }> = ({
  shot,
  push = 0.035,
  overlay,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const s = interpolate(frame, [0, durationInFrames], [1, 1 + push]);
  const map: MapPoint = (p) => [WIDTH / 2 + (p[0] - WIDTH / 2) * s, HEIGHT / 2 + (p[1] - HEIGHT / 2) * s];
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <AbsoluteFill style={{ scale: s }}>
        <Video src={staticFile(`footage/${shot}.mp4`)} muted style={{ width: "100%", height: "100%" }} />
      </AbsoluteFill>
      <AbsoluteFill
        style={{ background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)" }}
      />
      {overlay ? overlay(map) : null}
    </AbsoluteFill>
  );
};
