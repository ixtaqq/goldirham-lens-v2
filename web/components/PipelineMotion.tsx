"use client";

import { useEffect } from "react";

import { MOTION_ENABLED } from "@/lib/motion-pref";

const PINNED = "(min-width: 64rem) and (prefers-reduced-motion: no-preference)";

/**
 * Pins the five steps on wide screens and marks the active one from scroll position. On narrow
 * screens each step activates as it scrolls in. Without this component the steps read in order.
 */
export function PipelineMotion({ steps }: { steps: number }) {
  useEffect(() => {
    if (!MOTION_ENABLED) return;
    const section = document.getElementById("pipeline");
    const track = section?.querySelector<HTMLElement>(".pipeline-track");
    const items = Array.from(section?.querySelectorAll<HTMLElement>("[data-step]") ?? []);
    const rail = Array.from(section?.querySelectorAll<HTMLElement>("[data-rail]") ?? []);
    if (!section || !track || items.length !== steps) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const pinned = window.matchMedia(PINNED);
    let frame = 0;
    let current = -1;
    let observer: IntersectionObserver | null = null;

    const activate = (index: number) => {
      if (index === current) return;
      current = index;
      items.forEach((item, i) => {
        if (i === index) item.dataset.active = "";
        else delete item.dataset.active;
        item.toggleAttribute("data-past", i < index);
      });
      rail.forEach((item, i) => item.toggleAttribute("data-current", i === index));
    };

    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = track.getBoundingClientRect();
        const travel = rect.height - window.innerHeight;
        const progress = Math.min(1, Math.max(0, -rect.top / Math.max(1, travel)));
        activate(Math.min(steps - 1, Math.floor(progress * steps)));
      });
    };

    const setup = () => {
      window.removeEventListener("scroll", onScroll);
      observer?.disconnect();
      current = -1;
      if (pinned.matches) {
        section.dataset.pinned = "";
        onScroll();
        window.addEventListener("scroll", onScroll, { passive: true });
      } else {
        delete section.dataset.pinned;
        observer = new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              if (entry.isIntersecting) (entry.target as HTMLElement).dataset.active = "";
            }
          },
          { rootMargin: "0px 0px -25% 0px" },
        );
        items.forEach((item) => observer?.observe(item));
      }
    };

    setup();
    pinned.addEventListener("change", setup);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      observer?.disconnect();
      pinned.removeEventListener("change", setup);
      delete section.dataset.pinned;
    };
  }, [steps]);

  return null;
}
