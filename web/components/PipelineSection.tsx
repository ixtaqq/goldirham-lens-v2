import { demo, type Arrival } from "@/lib/demo";
import { tracePath } from "@/lib/geometry";
import { sectionKind } from "@/lib/telegram";

import { Check, Cross, Dash } from "./Icons";
import { PipelineMotion } from "./PipelineMotion";
import { TelegramText } from "./TelegramText";

const story = demo.pipeline;
const setupDay = demo.days.find((d) => d.id === "setup");

const QUALITY: Record<Arrival["quality"], { tone: string; text: string }> = {
  verified: { tone: "text-mint", text: "verified against a second source" },
  single_source: { tone: "text-fog", text: "one source, allowed for Bursa" },
  disputed: { tone: "text-loss", text: "sources disagree" },
  suspect: { tone: "text-loss", text: "suspect move" },
  invalid: { tone: "text-loss", text: "invalid bar" },
  corporate_action_pending: { tone: "text-loss", text: "possible split" },
};

function QualityMark({ quality }: { quality: Arrival["quality"] }) {
  const tone = `size-3 ${QUALITY[quality].tone}`;
  if (quality === "verified") return <Check className={tone} />;
  if (quality === "single_source") return <Dash className={tone} />;
  return <Cross className={tone} />;
}

function Arrivals({ checked }: { checked: boolean }) {
  return (
    <div
      className="overflow-x-auto"
      tabIndex={0}
      role="region"
      aria-label={checked ? "Quality check table" : "Arrivals table"}
    >
    <table className="figure w-full min-w-[19rem] text-left text-[0.8125rem]">
      <caption className="sr-only">
        {checked ? "Quality check on the newest bar of each asset" : "Newest bar of each asset as it arrives"}
      </caption>
      <thead className="label">
        <tr className="border-b border-rule">
          <th scope="col" className="py-2 pr-3 font-normal">Asset</th>
          <th scope="col" className="py-2 pr-3 font-normal">Session</th>
          <th scope="col" className="py-2 pr-3 text-right font-normal">Close</th>
          <th scope="col" className="py-2 font-normal">{checked ? "Check" : "Source"}</th>
        </tr>
      </thead>
      <tbody>
        {story.arrivals.map((a, index) => (
          <tr
            key={a.symbol}
            className={`step-row border-b border-rule ${checked && !a.ready ? "row-withheld" : ""}`}
            style={{ "--i": index } as React.CSSProperties}
          >
            <th scope="row" className="py-2 pr-3 font-normal text-paper">{a.symbol}</th>
            <td className="py-2 pr-3 text-fog">{a.session}</td>
            <td className="row-close relative py-2 pr-3 text-right text-paper">
              {a.close}
              {checked && !a.ready ? <span className="strike absolute inset-x-0 top-1/2 h-px bg-loss" aria-hidden="true" /> : null}
            </td>
            <td className="py-2">
              {checked ? (
                <span className="step-mark inline-flex items-center gap-2">
                  <QualityMark quality={a.quality} />
                  <span className={`${QUALITY[a.quality].tone} [overflow-wrap:anywhere]`}>
                    {a.reasons[0] ? <code>{a.reasons[0].code}</code> : QUALITY[a.quality].text}
                  </span>
                </span>
              ) : (
                <span className="text-fog">demo feed</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

function IndicatorChart() {
  const box = { width: 560, height: 220, pad: 12 };
  const line = (values: (number | null)[]) => {
    const firstIndex = values.findIndex((v) => v !== null);
    const present = values.slice(firstIndex).map((v) => v ?? 0);
    const width = (box.width * present.length) / values.length;
    return { d: tracePath(present, { ...box, width }), x: box.width - width };
  };
  const series = [
    { name: "close", ...line(story.series.close), stroke: "var(--color-paper)", width: 1.5 },
    { name: "50-session average", ...line(story.series.sma50), stroke: "var(--color-mint)", width: 1.25 },
    { name: "200-session average", ...line(story.series.sma200), stroke: "var(--color-fog)", width: 1.25 },
  ];
  return (
    <figure className="flex flex-col gap-3">
      <svg viewBox={`0 0 ${box.width} ${box.height}`} className="w-full" role="img" aria-label={`${story.indicators.symbol} close with its 50 and 200 session averages, last 120 sessions`}>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={box.width} y1={box.height * f} y2={box.height * f} stroke="var(--color-rule)" />
        ))}
        {series.map((s) => (
          <path
            key={s.name}
            className="chart-line"
            pathLength={1}
            d={s.d}
            transform={`translate(${s.x} 0)`}
            fill="none"
            stroke={s.stroke}
            strokeWidth={s.width}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <figcaption className="note flex flex-wrap gap-x-5 gap-y-1">
        {series.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-2">
            <span className="inline-block h-px w-4" style={{ background: s.stroke }} aria-hidden="true" />
            {s.name}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

function Rules() {
  return (
    <div className="grid gap-6 sm:grid-cols-2">
      {story.rules.map((rule) => (
        <div key={rule.symbol}>
          <p className="figure mb-2 text-sm text-paper">{rule.symbol}</p>
          <ol className="figure flex flex-col text-[0.8125rem]">
            {rule.trail.map((step, index) => (
              <li
                key={step.code}
                className="step-row flex items-start gap-2 border-b border-rule py-1.5"
                style={{ "--i": index } as React.CSSProperties}
              >
                <span className={`mt-1 ${step.passed ? "text-mint" : "text-loss"}`}>
                  {step.passed ? <Check /> : <Cross />}
                </span>
                <span className="min-w-0 [overflow-wrap:anywhere]">
                  <code className="text-paper">{step.code}</code>
                  <span className="block font-sans text-fog">{step.label}</span>
                </span>
                <span className="sr-only">{step.passed ? "passed" : "failed"}</span>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

function Assembly() {
  const sections = (setupDay?.sections ?? []).filter((html) =>
    ["header", "data", "setups"].includes(sectionKind(html)),
  );
  return (
    <article aria-label="Telegram message, setup day" className="border border-rule-strong bg-graphite">
      <header className="label flex justify-between border-b border-rule px-4 py-2">
        <span className="text-paper">Goldirham Lens bot</span>
        <span>{setupDay?.sent}</span>
      </header>
      <div className="tg flex flex-col gap-3 px-4 py-3 text-[0.875rem] leading-[1.5]">
        {sections.map((html, index) => (
          <section key={index} className="step-row" style={{ "--i": index * 2 } as React.CSSProperties}>
            <TelegramText html={html} />
          </section>
        ))}
      </div>
    </article>
  );
}

const STEPS = [
  {
    name: "Collect",
    title: "Completed sessions arrive",
    body: "Only bars whose exchange session has closed are read. Each one carries its source and session date from the moment it arrives.",
    visual: <Arrivals checked={false} />,
  },
  {
    name: "Check",
    title: "Every bar is checked before it counts",
    body: "Closes are compared with a second source. Bursa has one free source, so its bars are marked single source. Fern's close disagrees with its cross-check, so Fern is withheld with the reason code, not guessed at.",
    visual: <Arrivals checked />,
  },
  {
    name: "Measure",
    title: "Indicators come from verified bars only",
    body: "Averages, RSI and ATR are computed in Python from the bars that passed. Kestrel Systems has pulled back inside an uptrend.",
    visual: <IndicatorChart />,
  },
  {
    name: "Decide",
    title: "Every rule is evaluated and recorded",
    body: "Each rule leaves a reason code, pass or fail, so the reasoning for any asset can be replayed with /why. Kestrel passes. Orbit Foods has no pullback, so it waits.",
    visual: <Rules />,
  },
  {
    name: "Send",
    title: "Python renders the message",
    body: `The setup's levels are rounded to the exchange's price increment before any rule sees them: entry ${story.setup.entry}, stop ${story.setup.stop}, reward to risk ${story.setup.reward_risk}. Then the message is sent in Telegram-sized parts.`,
    visual: <Assembly />,
  },
];

export function PipelineSection() {
  return (
    <section id="pipeline" aria-labelledby="pipeline-title" className="pipeline border-t border-rule bg-carbon/80">
      <div className="shell pt-16 md:pt-24">
        <div className="grid gap-6 md:grid-cols-12">
          <h2 id="pipeline-title" className="font-display text-section font-semibold md:col-span-6">
            How a briefing is made
          </h2>
          <p className="max-w-[40rem] text-paper/85 md:col-span-6 md:pt-3">
            The setup day from the demo, step by step. Nothing here is drawn for the page: each table
            and line comes from the export the pipeline wrote.
          </p>
        </div>
      </div>
      <div className="pipeline-track">
        <div className="pipeline-stage">
          <div className="shell h-full">
            <ol className="pipeline-rail label hidden" aria-hidden="true">
              {STEPS.map((step, index) => (
                <li key={step.name} data-rail={index}>
                  {step.name}
                </li>
              ))}
            </ol>
            <ol className="pipeline-steps">
              {STEPS.map((step, index) => (
                <li key={step.name} className="step grid gap-6 py-12 md:grid-cols-12 md:gap-8" data-step={index}>
                  <div className="min-w-0 md:col-span-4">
                    <h3 className="font-display text-3xl font-semibold leading-none">{step.title}</h3>
                    <p className="mt-4 max-w-[38ch] text-paper/85">{step.body}</p>
                  </div>
                  <div className="step-visual min-w-0 md:col-span-8 lg:col-span-7 lg:col-start-6">{step.visual}</div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
      <PipelineMotion steps={STEPS.length} />
    </section>
  );
}
