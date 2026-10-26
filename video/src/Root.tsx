import React from "react";
import { Composition, Folder } from "remotion";
import { Film, SCENE_COMPONENTS } from "./Film";
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
  </>
);
