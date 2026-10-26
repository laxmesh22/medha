import React from "react";
import { Composition, Folder } from "remotion";
import { Film, SCENE_COMPONENTS } from "./Film";
import { Guide, GuideStep } from "./guide/Guide";
import { GUIDE_TOTAL, STEPS, stepFrames } from "./guide/steps";
import { FPS, HEIGHT, SCENES, TOTAL_FRAMES, WIDTH } from "./timeline";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="PhysioBuddyFilm" component={Film} durationInFrames={TOTAL_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Folder name="Scenes">
      {SCENES.map((s) => (
        <Composition
          key={s.id}
          id={`scene-${s.id}`}
          component={SCENE_COMPONENTS[s.id]}
          durationInFrames={s.duration}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
      ))}
    </Folder>
    <Composition id="AssemblyGuide" component={Guide} durationInFrames={GUIDE_TOTAL} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Folder name="GuideSteps">
      {STEPS.map((s) => (
        <Composition
          key={s.id}
          id={`step-${s.id}`}
          component={GuideStep}
          defaultProps={{ step: s }}
          durationInFrames={stepFrames(s)}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
      ))}
    </Folder>
  </>
);
