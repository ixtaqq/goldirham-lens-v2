import type { Table } from "@/lib/demo";

import { DocText } from "./TelegramText";

/** A table read from docs/STRATEGY.md by the export. The first row is the header. */
export function LedgerTable({ table, caption }: { table: Table; caption: string }) {
  const [head, ...rows] = table;
  if (!head) return null;
  return (
    <div className="overflow-x-auto border-t border-rule-strong" tabIndex={0} role="region" aria-label={caption}>
      <table className="w-full min-w-[34rem] border-collapse text-left text-[0.9375rem]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-rule">
            {head.map((cell) => (
              <th key={cell} scope="col" className="label py-3 pr-6 font-normal">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="lift border-b border-rule align-top transition-colors">
              {row.map((cell, c) =>
                c === 0 ? (
                  <th key={c} scope="row" className="py-3 pr-6 font-medium text-paper">
                    <DocText text={cell} />
                  </th>
                ) : (
                  <td key={c} className="py-3 pr-6 text-paper/85">
                    <DocText text={cell} />
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
