import { describe, expect, it } from "vitest";

import { BOOT_SCRIPT, MOTION_KEY, writeChoice, type StorageLike } from "@/lib/motion-pref";

function memory(): StorageLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
  };
}

const throwing: StorageLike = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("QuotaExceededError");
  },
};

function boot(local: StorageLike, session: StorageLike, reduced = false): string[] {
  const classes = new Set<string>();
  const env = {
    document: { documentElement: { classList: { add: (c: string) => classes.add(c) } } },
    window: { matchMedia: () => ({ matches: reduced }) },
    localStorage: local,
    sessionStorage: session,
  };
  new Function("document", "window", "localStorage", "sessionStorage", BOOT_SCRIPT)(
    env.document,
    env.window,
    env.localStorage,
    env.sessionStorage,
  );
  return [...classes].sort();
}

describe("motion preference", () => {
  it("writes the pause and the head script applies it before paint", () => {
    const store = memory();
    expect(writeChoice(() => store, "paused")).toBe(true);
    expect(store.data.get(MOTION_KEY)).toBe("paused");
    expect(boot(store, memory())).toEqual(["motion-paused"]);
  });

  it("plays the hero once per session, and never under reduced motion", () => {
    expect(boot(memory(), memory())).toEqual(["hero-play"]);
    const seen = memory();
    seen.setItem("lens-hero", "1");
    expect(boot(memory(), seen)).toEqual([]);
    expect(boot(memory(), memory(), true)).toEqual([]);
  });

  it("survives storage that throws", () => {
    expect(writeChoice(() => throwing, "paused")).toBe(false);
    expect(writeChoice(() => undefined, "paused")).toBe(true);
    expect(boot(throwing, throwing)).toEqual(["hero-play"]);
  });
});
