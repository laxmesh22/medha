import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { AngleHud } from "../components/AngleHud";
import { Callout } from "../components/Callout";
import { Footage } from "../components/Footage";
import { SceneTitle } from "../components/SceneTitle";
import { point } from "../track";

export const Reveal: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Footage
      shot="reveal"
      push={0.02}
      overlay={(map) => (
        <AbsoluteFill>
          <Callout anchor={map(point("reveal", "upperarm", frame))} label="Upper arm" sub="humerus angle + haptic cue" dx={-190} dy={-90} start={40} />
          <Callout anchor={map(point("reveal", "forearm", frame))} label="Forearm" sub="rotation the camera can't see" dx={-150} dy={70} start={52} />
          <Callout anchor={map(point("reveal", "trunk", frame))} label="Waist" sub="trunk reference" dx={250} dy={40} start={64} />
          <SceneTitle kicker="Worn in the clinic" title="Three straps, one rail" align="left" delay={14} />
        </AbsoluteFill>
      )}
    />
  );
};

const Exercise: React.FC<{
  shot: "flexion" | "abduction" | "rotation";
  exercise: string;
  field: "elevation" | "rotation";
  source: string;
  max: number;
  pod: "upperarm" | "forearm";
  podLabel: string;
  podSub: string;
  dx: number;
  dy: number;
  hud: "left" | "right";
}> = ({ shot, exercise, field, source, max, pod, podLabel, podSub, dx, dy, hud }) => {
  const frame = useCurrentFrame();
  return (
    <Footage
      shot={shot}
      push={0.025}
      overlay={(map) => (
        <AbsoluteFill>
          <AngleHud shot={shot} field={field} exercise={exercise} source={source} max={max} side={hud} />
          <Callout anchor={map(point(shot, pod, frame))} label={podLabel} sub={podSub} dx={dx} dy={dy} start={20} end={150} />
        </AbsoluteFill>
      )}
    />
  );
};

export const Flexion: React.FC = () => (
  <Exercise
    shot="flexion"
    exercise="Forward raise"
    field="elevation"
    source="upper-arm pod"
    max={180}
    pod="upperarm"
    podLabel="Upper-arm pod"
    podSub="moves rigidly with the humerus"
    dx={-165}
    dy={-120}
    hud="right"
  />
);

export const Abduction: React.FC = () => (
  <Exercise
    shot="abduction"
    exercise="Side raise"
    field="elevation"
    source="upper-arm pod"
    max={180}
    pod="upperarm"
    podLabel="Upper-arm pod"
    podSub="elevation in the side plane"
    dx={-250}
    dy={260}
    hud="right"
  />
);

export const Rotation: React.FC = () => (
  <Exercise
    shot="rotation"
    exercise="Outward rotation"
    field="rotation"
    source="forearm pod"
    max={90}
    pod="forearm"
    podLabel="Forearm pod"
    podSub="elbow at 90°, forearm swings out"
    dx={260}
    dy={-60}
    hud="left"
  />
);
