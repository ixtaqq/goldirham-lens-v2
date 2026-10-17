"use client";

import { AnimatePresence, domMax, LazyMotion, m, MotionConfig } from "motion/react";
import { useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react";

import type { Day, DayId } from "@/lib/demo";
import { MOTION_ENABLED } from "@/lib/motion-pref";
import { groupSections, sectionKind } from "@/lib/telegram";

import { DayNotes, MessageHeader, Messages, sectionKey } from "./DayView";
import { TelegramText } from "./TelegramText";

const EASE_OUT = [0.23, 1, 0.32, 1] as const;

function LiveMessages({ day }: { day: Day }) {
  const groups = groupSections(day.sections, day.messages);
  return (
    <div className="flex flex-col gap-3" data-reveal-group>
      {groups.map((group, index) => (
        <m.article
          layout="position"
          key={index}
          aria-label={`Telegram message ${index + 1} of ${groups.length}`}
          className="border border-rule-strong bg-graphite"
        >
          <MessageHeader sent={day.sent} />
          <div className="tg flex flex-col gap-4 px-4 pb-4 text-[0.9375rem] leading-[1.55] sm:px-5">
            <AnimatePresence mode="popLayout" initial={false}>
              {group.map((i, order) => {
                const html = day.sections[i] ?? "";
                return (
                  <m.section
                    key={sectionKey(html)}
                    layout="position"
                    data-kind={sectionKind(html)}
                    initial={{ opacity: 0, transform: "translateY(6px)" }}
                    animate={{ opacity: 1, transform: "translateY(0px)" }}
                    exit={{ opacity: 0, transition: { duration: 0.14 } }}
                    transition={{ duration: 0.28, ease: EASE_OUT }}
                  >
                    <div data-item style={{ "--i": order } as React.CSSProperties}>
                      <TelegramText html={html} />
                    </div>
                  </m.section>
                );
              })}
            </AnimatePresence>
          </div>
        </m.article>
      ))}
    </div>
  );
}

function subscribeHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

export function DaySwitcher({ days, intro }: { days: Day[]; intro: ReactNode }) {
  const [chosen, setChosen] = useState<DayId | null>(null);
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash, () => "");
  const tabs = useRef<(HTMLAnchorElement | null)[]>([]);
  const active = chosen ?? days.find((d) => `#day-${d.id}` === hash)?.id ?? "quiet";
  const day = days.find((d) => d.id === active) ?? days[0];

  if (!day) return null;

  function select(id: DayId, focus = false) {
    setChosen(id);
    window.history.replaceState(null, "", `#day-${id}`);
    if (focus) tabs.current[days.findIndex((d) => d.id === id)]?.focus();
  }

  function onKey(event: KeyboardEvent<HTMLAnchorElement>, index: number) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (event.key === "Home" || event.key === "End" || step) {
      event.preventDefault();
      const next =
        event.key === "Home" ? 0 : event.key === "End" ? days.length - 1 : (index + (step ?? 0) + days.length) % days.length;
      const target = days[next];
      if (target) select(target.id, true);
    }
  }

  return (
    <MotionConfig reducedMotion="user">
      <LazyMotion features={domMax} strict>
        <div className="days">
          <div role="tablist" aria-label="Demo days" className="-mx-4 grid grid-cols-3 border-y border-rule bg-carbon sm:mx-0 sm:border-x">
            {days.map((d, index) => (
              <a
                key={d.id}
                ref={(node) => {
                  tabs.current[index] = node;
                }}
                id={`tab-${d.id}`}
                href={`#day-${d.id}`}
                role="tab"
                aria-selected={d.id === active}
                aria-controls="day-panel"
                tabIndex={d.id === active ? 0 : -1}
                data-day={d.id}
                onClick={(event) => {
                  event.preventDefault();
                  select(d.id);
                }}
                onKeyDown={(event) => onKey(event, index)}
                className="day-tab press relative flex flex-col gap-0.5 border-r border-rule px-3 py-3 text-left no-underline last:border-r-0 sm:px-5"
              >
                <span className="label hidden sm:block">{d.date_label}</span>
                <span className="font-display text-xl font-semibold text-paper sm:text-2xl">{d.title}</span>
                <span className="day-tab-rule absolute inset-x-0 bottom-0 h-px bg-paper" aria-hidden="true" />
              </a>
            ))}
          </div>

          <div id="day-panel" role="tabpanel" aria-labelledby={`tab-${day.id}`} className="mt-8">
            <div id="day-quiet" className="day-live grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,36rem)] lg:gap-16">
              <div className="flex flex-col gap-10 self-start lg:sticky lg:top-24">
                {intro}
                <div data-day-content>
                  <DayNotes day={day} />
                </div>
              </div>
              <div data-day-content>
                {MOTION_ENABLED ? <LiveMessages day={day} /> : <Messages day={day} />}
              </div>
            </div>
            <noscript>
              {days
                .filter((d) => d.id !== "quiet")
                .map((d) => (
                  <div
                    key={d.id}
                    id={`day-${d.id}`}
                    className="day-fallback mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,36rem)] lg:gap-16"
                  >
                    <DayNotes day={d} />
                    <Messages day={d} />
                  </div>
                ))}
            </noscript>
          </div>
        </div>
      </LazyMotion>
    </MotionConfig>
  );
}
