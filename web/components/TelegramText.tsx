import type { ReactNode } from "react";

import { parse, type TgNode } from "@/lib/telegram";

function render(nodes: TgNode[], prefix: string): ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${prefix}${index}`;
    if (node.kind === "text") return node.text;
    const children = render(node.children, `${key}.`);
    if (node.kind === "b") return <strong key={key}>{children}</strong>;
    if (node.kind === "i") return <em key={key}>{children}</em>;
    if (node.kind === "pre") return <pre key={key}>{children}</pre>;
    if (node.kind === "blockquote") return <blockquote key={key}>{children}</blockquote>;
    return <code key={key}>{children}</code>;
  });
}

/** The Python renderer's Telegram HTML, as React elements. Never injected as raw HTML. */
export function TelegramText({ html }: { html: string }) {
  return <>{render(parse(html), "")}</>;
}

/** Backtick spans in the STRATEGY.md tables become inline code. */
export function DocText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("`") && part.endsWith("`") ? (
          <code key={index} className="text-paper">
            {part.slice(1, -1)}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}
