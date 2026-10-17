import { Mark } from "./Mark";

const WORDS = ["Numbers", "before", "narrative."];

export function Hero() {
  return (
    <section id="top" aria-labelledby="hero-title" className="relative">
      <div className="shell grid grid-cols-12 items-end gap-x-4 pt-14 pb-12 md:min-h-[calc(100svh-12.5rem)] md:pt-20">
        <div className="col-span-12 md:col-span-8 lg:col-span-7">
          <h1
            id="hero-title"
            className="font-display text-display font-semibold tracking-[-0.01em] text-paper"
          >
            {WORDS.map((word, index) => (
              <span
                key={word}
                className={`word inline-block ${index === WORDS.length - 1 ? "word-last" : ""}`}
                style={{ "--i": index } as React.CSSProperties}
              >
                {word}
                {index < WORDS.length - 1 ? " " : null}
              </span>
            ))}
          </h1>
          <p className="mt-6 max-w-[36rem] text-lede text-paper/85">
            One Telegram briefing a day for one investor in Malaysia, covering crypto, US stocks and
            Bursa Malaysia. Python computes and checks every figure before it is sent. A language
            model may write words, never numbers.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href="#briefing"
              className="press inline-flex items-center border border-paper bg-paper px-5 py-3 text-sm font-medium text-carbon no-underline hover:bg-paper/90"
            >
              Read a sample briefing
            </a>
            <a
              href="#pipeline"
              className="press inline-flex items-center border border-rule-strong px-5 py-3 text-sm font-medium text-paper no-underline hover:border-paper"
            >
              See how one is made
            </a>
          </div>
        </div>
        <div className="col-span-12 mt-10 flex justify-end md:col-span-4 md:mt-0 md:justify-center lg:col-span-5 lg:justify-end">
          <figure className="relative w-full max-w-[10rem] md:max-w-[18rem] lg:max-w-[22rem]" data-verify-frame>
            <Mark id="mark-hero" className="w-full" />
            <figcaption className="label mt-3 flex flex-wrap justify-between gap-x-4 border-t border-rule pt-2">
              <span className="whitespace-nowrap">verification frame</span>
              <span className="whitespace-nowrap text-mint">verified</span>
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}
