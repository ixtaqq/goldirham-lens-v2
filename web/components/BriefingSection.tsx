import { demo } from "@/lib/demo";

import { DaySwitcher } from "./DaySwitcher";

export function BriefingSection() {
  return (
    <section id="briefing" aria-labelledby="briefing-title" className="border-t border-rule bg-carbon/80">
      <div className="shell pb-16 md:pb-24">
        <DaySwitcher
          days={demo.days}
          intro={
            <div className="flex flex-col gap-4">
              <h2 id="briefing-title" className="font-display text-section font-semibold">
                Three mornings from the demo market
              </h2>
              <p className="max-w-[40ch] text-paper/85">
                Each message is the Telegram text the real renderer produced from the pipeline, run over
                a synthetic market. Switch days to see what changes. On most days the answer is
                nothing, and the briefing says so once.
              </p>
            </div>
          }
        />
        <p className="note mt-8">{demo.notice}</p>
      </div>
    </section>
  );
}
