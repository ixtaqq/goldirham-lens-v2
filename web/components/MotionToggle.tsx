"use client";

import { useSyncExternalStore } from "react";

import { writeChoice, type MotionChoice } from "@/lib/motion-pref";

export const MOTION_EVENT = "lens:motion";

const storage = () => (typeof window === "undefined" ? undefined : window.localStorage);

// The head script applies the stored choice as a class before paint; the class is the source.
function subscribe(onChange: () => void) {
  window.addEventListener(MOTION_EVENT, onChange);
  return () => window.removeEventListener(MOTION_EVENT, onChange);
}
const snapshot = (): MotionChoice =>
  document.documentElement.classList.contains("motion-paused") ? "paused" : "on";
const serverSnapshot = (): MotionChoice => "on";

/** WCAG 2.2.2: the background moves for more than five seconds, so it must be pausable. */
export function MotionToggle() {
  const choice = useSyncExternalStore(subscribe, snapshot, serverSnapshot);

  function toggle() {
    const next: MotionChoice = choice === "paused" ? "on" : "paused";
    writeChoice(storage, next);
    document.documentElement.classList.toggle("motion-paused", next === "paused");
    window.dispatchEvent(new CustomEvent(MOTION_EVENT, { detail: next }));
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={choice === "paused"}
      aria-label="Pause motion"
      className="press label hidden items-center gap-2 border border-rule px-3 py-1.5 text-paper motion-safe:inline-flex hover:border-rule-strong"
    >
      <svg viewBox="0 0 12 12" className="size-3" aria-hidden="true">
        {choice === "paused" ? (
          <path d="M3 2 L10 6 L3 10 Z" fill="currentColor" />
        ) : (
          <path d="M3 2 H5 V10 H3 Z M7 2 H9 V10 H7 Z" fill="currentColor" />
        )}
      </svg>
      <span className="sm:hidden">{choice === "paused" ? "Play" : "Pause"}</span>
      <span className="hidden sm:inline">{choice === "paused" ? "Play motion" : "Pause motion"}</span>
    </button>
  );
}
