// The visitor's Pause motion choice. Storage can be missing or throw (private mode, blocked
// site data), so every access is guarded and the page works without it.

export const MOTION_KEY = "lens-motion";
export type MotionChoice = "on" | "paused";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function writeChoice(storage: () => StorageLike | undefined, choice: MotionChoice): boolean {
  try {
    storage()?.setItem(MOTION_KEY, choice);
    return true;
  } catch {
    return false;
  }
}

/** Build-time switch for the whole motion layer. `NEXT_PUBLIC_MOTION=off` ships the static page. */
export const MOTION_ENABLED = process.env.NEXT_PUBLIC_MOTION !== "off";

export const HERO_KEY = "lens-hero";

// Runs in <head> before first paint. It only sets the paused state and starts the hero's CSS
// animation, which finishes on its own. Reveal gating (motion-ready) waits for hydration, so a
// bundle that fails to load can never leave content hidden.
export const BOOT_SCRIPT = `(function(){var d=document.documentElement;var p=false;try{p=localStorage.getItem("${MOTION_KEY}")==="paused"}catch(e){}if(p)d.classList.add("motion-paused");var r=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;var s=false;try{s=sessionStorage.getItem("${HERO_KEY}")==="1"}catch(e){}if(!r&&!p&&!s)d.classList.add("hero-play")})();`;
