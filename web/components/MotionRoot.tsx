"use client";

import { useEffect } from "react";

import { HERO_KEY, MOTION_ENABLED } from "@/lib/motion-pref";

const TARGETS = "[data-reveal-group], [data-chart]";

/**
 * Adds `motion-ready` after hydration and reveals elements as they scroll in. Anything already on
 * screen is marked shown first, so turning reveal gating on never hides what the visitor sees.
 */
export function MotionRoot() {
  useEffect(() => {
    if (!MOTION_ENABLED) return;
    const html = document.documentElement;
    try {
      sessionStorage.setItem(HERO_KEY, "1");
    } catch {}
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const elements = Array.from(document.querySelectorAll<HTMLElement>(TARGETS));
    const inView = (element: HTMLElement) => {
      const rect = element.getBoundingClientRect();
      return rect.top < window.innerHeight && rect.bottom > 0;
    };
    const pending = elements.filter((element) => {
      if (!inView(element)) return true;
      element.dataset.shown = "";
      return false;
    });
    html.classList.add("motion-ready");

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          (entry.target as HTMLElement).dataset.shown = "";
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -12% 0px" },
    );
    pending.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  return null;
}
