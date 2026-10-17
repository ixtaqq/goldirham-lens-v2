import { describe, expect, it } from "vitest";

import { linearScale, stepPath, tracePath } from "@/lib/geometry";
import { layoutFor, verifyPulse, VERIFY_EVERY_MS, VERIFY_WINDOW_MS } from "@/lib/field";

describe("tracePath", () => {
  it("maps 0..1 values onto the box, top is high", () => {
    expect(tracePath([0, 1, 0.5], { width: 100, height: 50 })).toBe("M0 50 L50 0 L100 25");
  });

  it("is empty for no values", () => {
    expect(tracePath([], { width: 10, height: 10 })).toBe("");
  });
});

describe("stepPath", () => {
  it("keeps zero inside the scale and steps once per value", () => {
    // min -1, max 2: y(v) = (2 - v) / 3 * 30
    const { d, zero } = stepPath([1, -1, 2], { width: 30, height: 30 });
    expect(zero).toBe(20);
    expect(d).toBe("M0 20 H10 V10 H20 V30 H30 V0");
  });

  it("scales negative values below the zero line", () => {
    const scale = linearScale([-2, 2], { width: 10, height: 40 });
    expect(scale.y(0)).toBe(20);
    expect(scale.y(-2)).toBe(40);
    expect(scale.y(2)).toBe(0);
  });
});

describe("signal field", () => {
  it("spreads traces across the viewport with 30 to 60 second cycles", () => {
    const layout = layoutFor(8);
    expect(layout[0]?.band).toBeCloseTo(0.14);
    expect(layout[7]?.band).toBeCloseTo(0.9);
    for (const l of layout) {
      expect(l.cycle).toBeGreaterThanOrEqual(30);
      expect(l.cycle).toBeLessThanOrEqual(60);
    }
  });

  it("verifies one trace every ten seconds and is quiet in between", () => {
    expect(verifyPulse(0).strength).toBe(0);
    expect(verifyPulse(VERIFY_WINDOW_MS * 0.4).strength).toBe(1);
    expect(verifyPulse(VERIFY_WINDOW_MS + 1).strength).toBe(0);
    expect(verifyPulse(VERIFY_EVERY_MS + 1000).trace).toBe(1);
  });

  it("never flashes: the envelope rises over at least 600ms", () => {
    const rise = VERIFY_WINDOW_MS * 0.2;
    expect(rise).toBeGreaterThanOrEqual(600);
  });
});
