// The brand loop and social card: the showcase's signal field and hero sequence, drawn per frame so
// the render is deterministic. Traces, layout, pulse timing and mark geometry come from web/lib and
// the demo fixture, so the video and the site show the same thing.

import { loadFont as loadDisplay } from "@remotion/google-fonts/BarlowCondensed";
import { loadFont as loadMono } from "@remotion/google-fonts/GeistMono";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

import demo from "../../web/data/demo.json";
import { BASE_ALPHA, layoutFor, verifyPulse } from "../../web/lib/field";
import { tracePath } from "../../web/lib/geometry";
import { MARK_FRAME, MARK_TRACE, MARK_VIEWBOX } from "../../web/lib/mark";

export const LOOP_FPS = 30;
export const LOOP_FRAMES = 15 * LOOP_FPS;

const { fontFamily: display } = loadDisplay("normal", { weights: ["600"], subsets: ["latin"] });
const { fontFamily: mono } = loadMono("normal", { weights: ["400"], subsets: ["latin"] });

const COLOR = { carbon: "#07110e", paper: "#f0eee7", fog: "#8d9992", mint: "#79d5c2" };
const WORDS = ["Numbers", "before", "narrative."];
const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);
const EASE_IN_OUT = Easing.bezier(0.77, 0, 0.175, 1);
const traces = demo.traces as number[][];
const layout = layoutFor(traces.length);

function progress(frame: number, from: number, length: number, easing = EASE_OUT) {
  return interpolate(frame, [from, from + length], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing,
  });
}

interface SceneProps {
  frame: number;
  fps: number;
  total: number;
  width: number;
  height: number;
}

/** One frame of the scene. The loop is seamless: every trace drifts exactly one tile per loop. */
function Scene({ frame, fps, total, width, height }: SceneProps) {
  const u = width / 1920;
  const markSize = 430 * u;
  const markX = width - markSize - 170 * u;
  const markY = height * 0.24;
  const unit = markSize / MARK_VIEWBOX;
  const box = {
    x: markX + MARK_FRAME.x * unit,
    y: markY + MARK_FRAME.y * unit,
    size: MARK_FRAME.size * unit,
  };
  const pulse = verifyPulse((frame / fps) * 1000);
  const verified = pulse.trace % traces.length;

  const drawFrame = progress(frame, 2, 15);
  const drawTrace = progress(frame, 11, 24, EASE_IN_OUT);
  const outro = progress(frame, total - 30, 28, EASE_IN_OUT);
  const markOpacity = 1 - outro;

  return (
    <AbsoluteFill style={{ backgroundColor: COLOR.carbon }}>
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <clipPath id="verify">
            <rect x={box.x} y={box.y} width={box.size} height={box.size} />
          </clipPath>
          <clipPath id="mark-frame">
            <rect x={MARK_FRAME.x} y={MARK_FRAME.y} width={MARK_FRAME.size} height={MARK_FRAME.size} />
          </clipPath>
        </defs>

        {Array.from({ length: 13 }, (_, i) => (
          <line
            key={`v${i}`}
            x1={(i * width) / 12}
            x2={(i * width) / 12}
            y1={0}
            y2={height}
            stroke={COLOR.fog}
            strokeOpacity={0.1}
          />
        ))}

        {traces.map((values, i) => {
          const l = layout[i];
          if (!l) return null;
          const tile = width * (1.15 + 0.1 * (i % 4));
          const shift = (frame / total) * tile + i * 37 * u;
          const h = l.amp * height;
          const top = l.band * height - h / 2;
          const d = tracePath(values, { width: tile, height: h });
          const copies = [0, 1].map((c) => `translate(${c * tile - (shift % tile)} ${top})`);
          return (
            <g key={i}>
              {copies.map((t) => (
                <path key={t} d={d} transform={t} fill="none" stroke={COLOR.fog} strokeOpacity={BASE_ALPHA} strokeWidth={1.5 * u} />
              ))}
              {i === verified && pulse.strength > 0 ? (
                <g clipPath="url(#verify)" opacity={pulse.strength * markOpacity}>
                  {copies.map((t) => (
                    <path key={t} d={d} transform={t} fill="none" stroke={COLOR.mint} strokeWidth={2.5 * u} />
                  ))}
                </g>
              ) : null}
            </g>
          );
        })}

        <g transform={`translate(${markX} ${markY}) scale(${unit})`} opacity={markOpacity}>
          <rect
            x={MARK_FRAME.x}
            y={MARK_FRAME.y}
            width={MARK_FRAME.size}
            height={MARK_FRAME.size}
            fill="none"
            stroke={COLOR.paper}
            strokeWidth={2}
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - drawFrame}
          />
          {[COLOR.fog, COLOR.mint].map((stroke) => (
            <path
              key={stroke}
              d={MARK_TRACE}
              fill="none"
              stroke={stroke}
              strokeWidth={3}
              pathLength={1}
              strokeDasharray={1}
              strokeDashoffset={1 - drawTrace}
              clipPath={stroke === COLOR.mint ? "url(#mark-frame)" : undefined}
            />
          ))}
        </g>
      </svg>

      <div
        style={{
          position: "absolute",
          left: 150 * u,
          bottom: height * 0.2,
          color: COLOR.paper,
          fontFamily: display,
          fontWeight: 600,
          fontSize: 176 * u,
          lineHeight: 0.9,
          letterSpacing: "-0.01em",
          width: 1100 * u,
        }}
      >
        {WORDS.map((word, i) => {
          const start = 27 + i * 2 + (i === WORDS.length - 1 ? 4 : 0);
          const shown = progress(frame, start, 13);
          const opacity = interpolate(shown * (1 - outro), [0, 1], [0.08, 1]);
          return (
            <span
              key={word}
              style={{
                display: "inline-block",
                opacity,
                transform: `translateY(${(1 - shown) * 0.12}em)`,
                marginRight: i < WORDS.length - 1 ? "0.22em" : 0,
              }}
            >
              {word}
            </span>
          );
        })}
      </div>

      <div
        style={{
          position: "absolute",
          left: 152 * u,
          bottom: height * 0.12,
          color: COLOR.fog,
          fontFamily: mono,
          fontSize: 26 * u,
          letterSpacing: "0.02em",
        }}
      >
        Goldirham Lens · one Telegram briefing a day · every figure computed in Python
      </div>
      <div
        style={{
          position: "absolute",
          left: 152 * u,
          top: 64 * u,
          color: COLOR.paper,
          fontFamily: mono,
          fontSize: 22 * u,
          letterSpacing: "0.04em",
          border: `${1.5 * u}px solid rgba(141, 153, 146, 0.42)`,
          padding: `${8 * u}px ${14 * u}px`,
        }}
      >
        {demo.label} · synthetic market
      </div>
    </AbsoluteFill>
  );
}

export function BrandLoop() {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  return <Scene frame={frame} fps={fps} total={durationInFrames} width={width} height={height} />;
}

/** The social card: the held state of the loop at the second verification moment. */
export function SocialCard() {
  const { width, height } = useVideoConfig();
  return <Scene frame={11 * LOOP_FPS} fps={LOOP_FPS} total={LOOP_FRAMES} width={width} height={height} />;
}
