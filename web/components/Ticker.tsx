import { demo } from "@/lib/demo";

const TONE = { up: "text-paper", down: "text-loss", flat: "text-fog" } as const;

function Row({ hidden }: { hidden?: boolean }) {
  return (
    <ul className="flex shrink-0 items-center" aria-hidden={hidden || undefined}>
      {demo.ticker.map((item) => (
        <li key={item.symbol} className="figure flex items-baseline gap-2 border-r border-rule px-5 text-xs">
          <span className="text-paper">{item.symbol}</span>
          <span className="text-fog">{item.close}</span>
          <span className={TONE[item.direction]}>{item.change}</span>
        </li>
      ))}
    </ul>
  );
}

export function Ticker() {
  return (
    <div className="ticker flex h-9 items-center overflow-hidden border-b border-rule bg-carbon">
      <p className="label z-10 flex h-full shrink-0 items-center border-r border-rule bg-carbon px-4 text-paper">
        {demo.label}
      </p>
      <div className="relative min-w-0 flex-1 overflow-hidden" role="group" aria-label="Demo closes, synthetic market">
        <div className="ticker-track flex">
          <Row />
          <Row hidden />
        </div>
      </div>
    </div>
  );
}
