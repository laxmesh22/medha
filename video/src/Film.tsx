import React from "react";
import { Audio } from "@remotion/media";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { AbsoluteFill, interpolate, Sequence, staticFile } from "remotion";
import { Abduction, Flexion, Reveal, Rotation } from "./scenes/BodyScenes";
import { Intro } from "./scenes/Intro";
import { Outro } from "./scenes/Outro";
import { Family, Product, Rail } from "./scenes/ProductScenes";
import { duration, RAIL_CLICK, SCENE_START, SceneId, SCENES, TOTAL_FRAMES, TRANSITION } from "./timeline";

export const SCENE_COMPONENTS: Record<SceneId, React.FC> = {
  intro: Intro,
  product: Product,
  rail: Rail,
  family: Family,
  reveal: Reveal,
  flexion: Flexion,
  abduction: Abduction,
  rotation: Rotation,
  outro: Outro,
};

// callouts that get a soft tick when they draw on: [scene, frame within the scene]
const TICKS: [SceneId, number][] = [
  ["product", 52],
  ["product", 60],
  ["product", 68],
  ["reveal", 40],
  ["reveal", 52],
  ["reveal", 64],
  ["flexion", 20],
  ["abduction", 20],
  ["rotation", 20],
];

const Soundtrack: React.FC = () => (
  <>
    <Audio
      src={staticFile("audio/bgm.wav")}
      volume={(f) => interpolate(f, [0, 10, TOTAL_FRAMES - 20, TOTAL_FRAMES], [0, 0.9, 0.9, 0], { extrapolateRight: "clamp" })}
    />
    {SCENES.slice(1).map((s) => (
      <Sequence key={`w-${s.id}`} from={SCENE_START[s.id] - 9} durationInFrames={24} layout="none">
        <Audio src={staticFile("audio/whoosh.wav")} volume={0.35} />
      </Sequence>
    ))}
    <Sequence from={SCENE_START.rail + RAIL_CLICK} durationInFrames={10} layout="none">
      <Audio src={staticFile("audio/click.wav")} volume={0.9} />
    </Sequence>
    {TICKS.map(([scene, f]) => (
      <Sequence key={`t-${scene}-${f}`} from={SCENE_START[scene] + f} durationInFrames={6} layout="none">
        <Audio src={staticFile("audio/tick.wav")} volume={0.35} />
      </Sequence>
    ))}
  </>
);

export const Film: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    <TransitionSeries>
      {SCENES.flatMap((s, i) => {
        const Scene = SCENE_COMPONENTS[s.id];
        const seq = (
          <TransitionSeries.Sequence key={s.id} name={s.id} durationInFrames={duration(s.id)}>
            <Scene />
          </TransitionSeries.Sequence>
        );
        return i < SCENES.length - 1
          ? [seq, <TransitionSeries.Transition key={`${s.id}-x`} presentation={fade()} timing={linearTiming({ durationInFrames: TRANSITION })} />]
          : [seq];
      })}
    </TransitionSeries>
    <Soundtrack />
  </AbsoluteFill>
);
