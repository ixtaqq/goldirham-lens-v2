// Layout of the signal field, shared by the WebGL renderer, the Canvas 2D fallback and the SVG
// poster, so all three draw the same traces from the same demo fixture.

export interface TraceLayout {
  /** Vertical centre as a fraction of the viewport height. */
  band: number;
  /** Peak-to-trough height as a fraction of the viewport height. */
  amp: number;
  /** Seconds for one full drift across a tile. */
  cycle: number;
}

export const TILE_FACTOR = 1.3;
export const PARALLAX_MAX = 24;
export const VERIFY_EVERY_MS = 10_000;
export const VERIFY_WINDOW_MS = 3_200;
export const BASE_ALPHA = 0.17;
export const LENS_ALPHA = 0.78;

export function layoutFor(count: number): TraceLayout[] {
  return Array.from({ length: count }, (_, index) => ({
    band: 0.14 + (index * 0.76) / Math.max(1, count - 1),
    amp: 0.15 + (index % 3) * 0.025,
    cycle: 36 + ((index * 7) % 19),
  }));
}

/** 0..1 envelope for the verification moment: rise, hold, fall inside each window. */
export function verifyPulse(elapsedMs: number): { trace: number; strength: number } {
  const cycle = Math.floor(elapsedMs / VERIFY_EVERY_MS);
  const within = elapsedMs - cycle * VERIFY_EVERY_MS;
  if (within > VERIFY_WINDOW_MS) return { trace: cycle, strength: 0 };
  const t = within / VERIFY_WINDOW_MS;
  const strength = t < 0.2 ? t / 0.2 : t < 0.55 ? 1 : Math.max(0, 1 - (t - 0.55) / 0.45);
  return { trace: cycle, strength };
}
