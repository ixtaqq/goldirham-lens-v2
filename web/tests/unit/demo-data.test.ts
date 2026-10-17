import { describe, expect, it } from "vitest";

import { demo } from "@/lib/demo";

describe("demo export", () => {
  it("is labelled as demo data", () => {
    expect(demo.label).toBe("DEMO DATA");
    expect(demo.notice).toMatch(/synthetic/);
  });

  it("has the quiet, setup and degraded days in order", () => {
    expect(demo.days.map((d) => d.id)).toEqual(["quiet", "setup", "degraded"]);
    expect(demo.days.map((d) => d.setups)).toEqual([[], ["KSTL"], []]);
  });

  it("tells the pipeline story the page narrates", () => {
    const fern = demo.pipeline.arrivals.find((a) => a.symbol === "FERN-USD");
    expect(fern).toMatchObject({ quality: "disputed", ready: false });
    expect(demo.pipeline.rules[0]?.trail.every((step) => step.passed)).toBe(true);
    expect(demo.pipeline.rules[1]?.trail.some((step) => !step.passed)).toBe(true);
    expect(demo.pipeline.series.close).toHaveLength(120);
  });

  it("gives the field one 0..1 trace per asset", () => {
    expect(demo.traces).toHaveLength(8);
    for (const trace of demo.traces) {
      expect(Math.min(...trace)).toBe(0);
      expect(Math.max(...trace)).toBe(1);
    }
  });

  it("carries the strategy tables with their headers", () => {
    expect(demo.method.rules[0]).toEqual(["Rule", "Passes when", "Reason codes"]);
    expect(demo.method.scorecard[0]?.[0]).toBe("Metric");
  });
});
