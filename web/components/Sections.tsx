import type { ReactNode } from "react";

import { demo } from "@/lib/demo";

import { LedgerTable } from "./LedgerTable";
import { TelegramText } from "./TelegramText";

export function SectionHead({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <div className="grid gap-6 md:grid-cols-12">
      <h2 id={id} className="font-display text-section font-semibold md:col-span-6">
        {title}
      </h2>
      <div className="max-w-[40rem] text-paper/85 md:col-span-6 md:pt-3">{children}</div>
    </div>
  );
}

export function MethodSection() {
  return (
    <section id="method" aria-labelledby="method-title" className="border-t border-rule bg-carbon/80">
      <div className="shell py-16 md:py-24">
        <SectionHead id="method-title" title="The rules, as the code runs them">
          <p>
            These tables are read from the project&apos;s strategy reference when the demo is
            exported, and CI fails if the export falls behind. Every rule is evaluated, so the reason
            codes for any asset can be replayed.
          </p>
          <p className="mt-3">
            In the real service no strategy sends setups until the owner activates a version that has
            a backtest report. The demo treats this one as live so the setup path is visible.
          </p>
        </SectionHead>
        <div className="mt-12 grid gap-14">
          <div className="min-w-0">
            <h3 className="mb-4 text-xl font-medium">pullback_in_uptrend</h3>
            <LedgerTable table={demo.method.rules} caption="Rules of the pullback in uptrend strategy" />
          </div>
          <div className="min-w-0">
            <h3 className="mb-4 text-xl font-medium">Holding reviews</h3>
            <LedgerTable table={demo.method.reviews} caption="Holding review rules and their actions" />
          </div>
        </div>
      </div>
    </section>
  );
}

export function ProvenanceSection() {
  const setup = demo.days.find((d) => d.id === "setup");
  const line = setup?.sections.find((s) => s.startsWith("<b>Setups</b>"))?.split("\n").at(-1) ?? "";
  return (
    <section id="provenance" aria-labelledby="provenance-title" className="border-t border-rule bg-carbon/70">
      <div className="shell py-16 md:py-24">
        <SectionHead id="provenance-title" title="Every figure says where it came from">
          <p>
            A figure without its source and session date is not shown. Missing data is printed as
            unavailable, and nothing is filled in from another value.
          </p>
        </SectionHead>

        <figure className="mt-12 border border-rule-strong bg-graphite p-5 md:p-8">
          <p className="tg figure text-lg md:text-2xl">
            <TelegramText html={line} />
          </p>
          <figcaption className="note mt-5 grid gap-3 border-t border-rule pt-4 sm:grid-cols-3">
            <span>
              <span className="text-paper">Source.</span> The provider that supplied the close.
            </span>
            <span>
              <span className="text-paper">Session.</span> The exchange session the close belongs to.
            </span>
            <span>
              <span className="text-paper">Quality.</span> The result of the checks below.
            </span>
          </figcaption>
        </figure>

        <div className="mt-14 grid gap-14">
          <div className="min-w-0">
            <h3 className="mb-4 text-xl font-medium">Bar quality</h3>
            <LedgerTable table={demo.method.quality} caption="Bar quality rules" />
          </div>
          <div className="min-w-0">
            <h3 className="mb-4 text-xl font-medium">Readiness</h3>
            <p className="mb-4 max-w-[60ch] text-paper/85">
              An asset can produce a setup only when its last 200 closed sessions are all present and
              usable. Each market follows its own exchange calendar.
            </p>
            <LedgerTable table={demo.method.readiness} caption="Exchange calendars per market" />
          </div>
        </div>
      </div>
    </section>
  );
}

const PRACTICES = [
  {
    title: "Two schedules, one briefing",
    body: "The daily job is scheduled at 07:00 and 07:40 Malaysia time. A per-day claim in the database makes the second run exit when the first succeeded.",
  },
  {
    title: "A dead-man's switch",
    body: "An outside monitor expects a success ping by 08:15. If none arrives, it alerts the owner through its own channel, even when the job never started.",
  },
  {
    title: "Held, never resent blindly",
    body: "If Telegram times out after part of a briefing was accepted, the briefing is held. The owner previews it and chooses to resend the rest or dismiss it.",
  },
  {
    title: "A briefing even without the database",
    body: "When the database is down, a reduced briefing goes out from live provider data and says what it had to skip.",
  },
  {
    title: "Backups that are restored",
    body: "Encrypted nightly backups, and a weekly drill that restores the newest one into a scratch database and compares row counts.",
  },
  {
    title: "Schema changes wait for approval",
    body: "Migrations run only from one workflow, after a backup, behind a required reviewer.",
  },
];

export function ReliabilitySection() {
  return (
    <section id="reliability" aria-labelledby="reliability-title" className="border-t border-rule bg-carbon/80">
      <div className="shell py-16 md:py-24">
        <SectionHead id="reliability-title" title="How every morning is kept">
          <p>
            These are practices built into the code and workflows. This page shows no live status,
            because it runs on demo data and never connects to the service.
          </p>
        </SectionHead>
        <dl className="mt-12 grid border-t border-rule-strong md:grid-cols-2">
          {PRACTICES.map((p, index) => (
            <div
              key={p.title}
              className="border-b border-rule py-6 md:odd:border-r md:odd:pr-8 md:even:pl-8"
             
              style={{ "--i": index % 2 } as React.CSSProperties}
            >
              <dt className="text-lg font-medium text-paper">{p.title}</dt>
              <dd className="mt-2 max-w-[52ch] text-paper/80">{p.body}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

const FAQ = [
  {
    q: "Does it place trades?",
    a: "No. It never connects to a broker and holds no keys that can trade. It is research and decision support for one person.",
  },
  {
    q: "Is this real market data?",
    a: "No. Every figure on this page comes from a synthetic market generated from a fixed seed and run through the real pipeline. The symbols and names are invented.",
  },
  {
    q: "Where do the numbers come from?",
    a: "Python computes every figure from completed daily sessions after the quality checks. The Telegram text is rendered by Python too.",
  },
  {
    q: "What does the AI do?",
    a: "By default, nothing. An optional narrative can be switched on. The model then sees a catalogue of facts and may refer to a number only through a placeholder, which Python fills in. A reply containing any digit of its own is discarded.",
  },
  {
    q: "Why are there no setups most days?",
    a: "Because most days nothing passes every rule on verified data. A briefing that says nothing new is the expected result.",
  },
  {
    q: "Do the rules work?",
    a: "Not yet shown. The first backtest on real history did not beat random entries with the same stops and targets, so no strategy is live in the real service. The demo backtest above reached the same verdict on synthetic data.",
  },
];

export function FaqSection() {
  return (
    <section id="faq" aria-labelledby="faq-title" className="border-t border-rule bg-carbon/70">
      <div className="shell py-16 md:py-24">
        <SectionHead id="faq-title" title="Questions">
          <p>Short answers. The repository holds the long ones.</p>
        </SectionHead>
        <div className="mt-12 border-t border-rule-strong">
          {FAQ.map((item) => (
            <details key={item.q} className="faq group border-b border-rule">
              <summary className="press flex cursor-pointer list-none items-center justify-between gap-6 py-5 text-lg font-medium [&::-webkit-details-marker]:hidden">
                {item.q}
                <span className="faq-icon relative size-3 shrink-0" aria-hidden="true">
                  <span className="absolute inset-x-0 top-1/2 h-px bg-paper" />
                  <span className="faq-icon-v absolute inset-y-0 left-1/2 w-px bg-paper" />
                </span>
              </summary>
              <p className="max-w-[62ch] pb-6 text-paper/85">{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  const footer = demo.days[0]?.sections.at(-1)?.split("\n")[0] ?? "";
  return (
    <footer className="border-t border-rule-strong bg-carbon">
      <div className="shell grid gap-6 py-12 md:grid-cols-12">
        <p className="font-display text-3xl font-semibold md:col-span-4">Goldirham Lens</p>
        <div className="flex flex-col gap-3 text-sm text-paper/80 md:col-span-8">
          <p className="tg">
            <TelegramText html={footer} />
          </p>
          <p className="note">
            {demo.label}. {demo.notice}
          </p>
        </div>
      </div>
    </footer>
  );
}
