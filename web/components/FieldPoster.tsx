import { demo } from "@/lib/demo";
import { BASE_ALPHA, layoutFor, TILE_FACTOR } from "@/lib/field";
import { tracePath } from "@/lib/geometry";

const WIDTH = 1600;
const HEIGHT = 1000;

/** The still version of the signal field, drawn at build time from the same fixture. */
export function FieldPoster() {
  const layout = layoutFor(demo.traces.length);
  const tile = WIDTH * TILE_FACTOR;
  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      {demo.traces.map((values, index) => {
        const l = layout[index];
        if (!l) return null;
        const height = l.amp * HEIGHT;
        const top = l.band * HEIGHT - height / 2;
        return (
          <path
            key={index}
            d={tracePath(values, { width: tile, height })}
            transform={`translate(${-index * 37} ${top})`}
            fill="none"
            stroke="var(--color-fog)"
            strokeOpacity={BASE_ALPHA}
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}
