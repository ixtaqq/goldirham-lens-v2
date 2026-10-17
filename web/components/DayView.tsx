import type { Day } from "@/lib/demo";
import { groupSections, sectionKind } from "@/lib/telegram";

import { TelegramText } from "./TelegramText";

export function DayNotes({ day }: { day: Day }) {
  return (
    <div className="flex flex-col gap-5">
      <h3 className="font-display text-4xl font-semibold">{day.title}</h3>
      <p className="max-w-[34ch] text-paper/85">{day.summary}</p>
      <dl className="label grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 border-t border-rule pt-4">
        <dt>Date</dt>
        <dd className="text-paper">{day.date_label}</dd>
        <dt>Data</dt>
        <dd className="flex items-center gap-2 text-paper">
          <span
            className={`status-dot inline-block size-2 ${day.healthy ? "bg-mint" : "bg-loss"}`}
            aria-hidden="true"
          />
          {day.healthy ? "every source verified" : "issues listed in the briefing"}
        </dd>
        <dt>Setups</dt>
        <dd className="text-paper">{day.setups.length ? day.setups.join(", ") : "none"}</dd>
        <dt>Sent</dt>
        <dd className="text-paper">{day.sent}</dd>
      </dl>
    </div>
  );
}

export function sectionKey(html: string): string {
  let hash = 5381;
  for (let i = 0; i < html.length; i += 1) hash = ((hash << 5) + hash + html.charCodeAt(i)) | 0;
  return `${sectionKind(html)}-${(hash >>> 0).toString(36)}`;
}

/** A static render of one day's Telegram messages. The animated version wraps the same markup. */
export function Messages({ day }: { day: Day }) {
  const groups = groupSections(day.sections, day.messages);
  return (
    <div className="flex flex-col gap-3">
      {groups.map((group, index) => (
        <article
          key={index}
          aria-label={`Telegram message ${index + 1} of ${groups.length}`}
          className="border border-rule-strong bg-graphite"
        >
          <MessageHeader sent={day.sent} />
          <div className="tg flex flex-col gap-4 px-4 pb-4 text-[0.9375rem] leading-[1.55] sm:px-5">
            {group.map((i) => (
              <section key={sectionKey(day.sections[i] ?? "")} data-kind={sectionKind(day.sections[i] ?? "")}>
                <TelegramText html={day.sections[i] ?? ""} />
              </section>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

export function MessageHeader({ sent }: { sent: string }) {
  return (
    <header className="label flex items-center justify-between border-b border-rule px-4 py-2 sm:px-5">
      <span className="text-paper">Goldirham Lens bot</span>
      <span>{sent}</span>
    </header>
  );
}
