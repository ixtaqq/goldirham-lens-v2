import { demo, type Summary } from "@/lib/demo";
import { linearScale, stepPath } from "@/lib/geometry";

import { LedgerTable } from "./LedgerTable";
import { SectionHead } from "./Sections";

const bt = demo.backtest;

function interval(s: Summary) {
  return s.expectancy_ci90_r ? `${s.expectancy_ci90_r[0]}R to ${s.expectancy_ci90_r[1]}R` : "n/a";
}

function CumulativeChart() {
  const box = { width: 720, height: 260, pad: 16 };
  const values = bt.cumulative_r.map((p) => p.r);
  const { d, zero } = stepPath(values, box);
  const step = box.width / Math.max(1, values.length);
  const oos = bt.cumulative_r.findIndex((p) => p.day >= bt.out_of_sample_from);
  const last = bt.cumulative_r.at(-1);
  return (
    <figure data-chart className="flex flex-col gap-3">
      <svg
        viewBox={`0 0 ${box.width} ${box.height}`}
        className="w-full overflow-visible"
        role="img"
        aria-label={`Cumulative outcome in R across ${values.length} resolved demo trades, ending at ${last?.label ?? "n/a"}`}
      >
        <line x1={0} x2={box.width} y1={zero} y2={zero} stroke="var(--color-rule-strong)" />
        {oos > 0 ? (
          <g>
            <line x1={oos * step} x2={oos * step} y1={0} y2={box.height} stroke="var(--color-rule-strong)" strokeDasharray="3 4" />
            <text x={oos * step + 6} y={14} className="label" fill="var(--color-fog)" fontSize={11}>
              out of sample from {bt.out_of_sample_from}
            </text>
          </g>
        ) : null}
        <path className="chart-line" pathLength={1} d={d} fill="none" stroke="var(--color-paper)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        {bt.cumulative_r.map((p, index) => (
          <g key={`${p.day}-${index}`} className="hit">
            <rect x={index * step} y={0} width={step} height={box.height} fill="transparent" />
            <g className="tip">
              <line x1={(index + 1) * step} x2={(index + 1) * step} y1={0} y2={box.height} stroke="var(--color-fog)" />
              <text
                x={Math.min((index + 1) * step + 6, box.width - 120)}
                y={box.height - 8}
                fill="var(--color-paper)"
                fontSize={11}
                fontFamily="var(--font-mono)"
              >
                {p.day} · {p.label}
              </text>
            </g>
          </g>
        ))}
      </svg>
      <div className="label flex justify-between" aria-hidden="true">
        <span>{bt.period[0]}</span>
        <span>{bt.period[1]}</span>
      </div>
      <figcaption className="note">
        Cumulative R after each resolved trade, exit model full_to_t2. Final {last?.label}. Hover for each
        exit.
      </figcaption>
    </figure>
  );
}

function ExpectancyBars() {
  const rows = [
    { name: "Hold to T2 or stop", value: bt.full_to_t2.all.expectancy_r ?? "0" },
    { name: "Half at T1, rest at breakeven", value: bt.half_at_t1_breakeven.all.expectancy_r ?? "0" },
    { name: "Random entries, same stops", value: bt.random_entry_baseline?.mean_expectancy_r ?? "0" },
  ];
  const box = { width: 320, height: 180, pad: 8 };
  const scale = linearScale(rows.map((r) => Number.parseFloat(r.value)), box);
  const width = 56;
  const gap = (box.width - width * rows.length) / (rows.length + 1);
  return (
    <figure data-chart className="flex flex-col gap-3">
      <svg viewBox={`0 0 ${box.width} ${box.height + 24}`} className="w-full max-w-[24rem]" role="img" aria-label="Expectancy per trade for two exit models and for random entries">
        <line x1={0} x2={box.width} y1={scale.y(0)} y2={scale.y(0)} stroke="var(--color-rule-strong)" />
        {rows.map((row, index) => {
          const v = Number.parseFloat(row.value);
          const top = Math.min(scale.y(v), scale.y(0));
          const height = Math.abs(scale.y(v) - scale.y(0));
          const x = gap + index * (width + gap);
          return (
            <g key={row.name}>
              <rect
                className="chart-bar"
                style={{ "--i": index } as React.CSSProperties}
                x={x}
                y={top}
                width={width}
                height={Math.max(1, height)}
                fill={index === 2 ? "var(--color-fog)" : "var(--color-paper)"}
              />
              <text x={x + width / 2} y={box.height + 18} textAnchor="middle" fill="var(--color-paper)" fontSize={12} fontFamily="var(--font-mono)">
                {row.value}R
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="note flex flex-col gap-1">
        {rows.map((row) => (
          <span key={row.name}>
            {row.value}R · {row.name}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export function ScorecardSection() {
  const all = bt.full_to_t2.all;
  const oos = bt.full_to_t2.out_of_sample;
  const facts: [string, string][] = [
    ["Resolved trades", String(all.resolved)],
    ["Expectancy per trade", `${all.expectancy_r}R`],
    ["90% interval", interval(all)],
    ["Win rate", `${all.win_rate_pct}%`],
    ["T1 reached", `${all.t1_touch_rate_pct}%`],
    ["Out of sample expectancy", `${oos.expectancy_r}R`],
    ["Random entries, mean", `${bt.random_entry_baseline?.mean_expectancy_r}R`],
  ];
  return (
    <section id="scorecard" aria-labelledby="scorecard-title" className="border-t border-rule bg-carbon/80">
      <div className="shell py-16 md:py-24">
        <SectionHead id="scorecard-title" title="A backtest that can say no">
          <p>
            The demo backtest replays the synthetic history through the same decision and evaluation
            code. Its report compares the rules against random entries with the same stops and targets.
          </p>
          <p className="mt-3">
            On this market the rules did not beat random entries. The first report on real history
            reached the same verdict, which is why no strategy is live in the real service.
          </p>
        </SectionHead>

        <div className="mt-12 grid gap-10 lg:grid-cols-12">
          <div className="min-w-0 lg:col-span-8">
            <CumulativeChart />
          </div>
          <div className="lg:col-span-4">
            <dl className="figure grid content-start gap-y-2 border-t border-rule-strong pt-4 text-sm">
              {facts.map(([name, value]) => (
                <div key={name} className="flex justify-between gap-4 border-b border-rule pb-2">
                  <dt className="font-sans text-fog">{name}</dt>
                  <dd className="text-paper">{value}</dd>
                </div>
              ))}
            </dl>
            <p className="label pt-3">
              {bt.strategy} {bt.version} · {bt.period[0]} to {bt.period[1]} · {demo.label}
            </p>
          </div>
        </div>

        <div className="mt-14 grid gap-10 lg:grid-cols-12">
          <div className="lg:col-span-4">
            <ExpectancyBars />
          </div>
          <div className="grid gap-8 lg:col-span-8">
            <div>
              <h3 className="mb-3 text-xl font-medium">What the report assumes</h3>
              <ul className="flex flex-col gap-1.5 text-paper/85">
                {bt.assumptions.map((a) => (
                  <li key={a} className="border-b border-rule pb-1.5">{a}</li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="mb-3 text-xl font-medium">What it cannot tell you</h3>
              <ul className="flex flex-col gap-1.5 text-paper/85">
                {bt.caveats.map((c) => (
                  <li key={c} className="border-b border-rule pb-1.5">{c}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="mt-14">
          <h3 className="mb-4 text-xl font-medium">Scorecard definitions</h3>
          <LedgerTable table={demo.method.scorecard} caption="Scorecard metric definitions" />
        </div>
      </div>
    </section>
  );
}
