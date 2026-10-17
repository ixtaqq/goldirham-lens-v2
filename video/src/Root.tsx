import { Composition, Still } from "remotion";

import { BrandLoop, LOOP_FRAMES, LOOP_FPS, SocialCard } from "./BrandLoop";

export function Root() {
  return (
    <>
      <Composition
        id="BrandLoop"
        component={BrandLoop}
        durationInFrames={LOOP_FRAMES}
        fps={LOOP_FPS}
        width={1920}
        height={1080}
      />
      <Still id="SocialCard" component={SocialCard} width={1200} height={630} />
    </>
  );
}
