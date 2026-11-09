// Parses the Telegram HTML subset the Python renderer emits (b, i, code, pre, blockquote) into a
// tree. Anything else is kept as literal text, so a stray tag can never become markup.

export type Mark = "b" | "i" | "code" | "pre" | "blockquote";

export type TgNode = { kind: "text"; text: string } | { kind: Mark; children: TgNode[] };

const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
};

export function decode(text: string): string {
  return text.replace(/&(amp|lt|gt|quot|#39);/g, (entity) => ENTITIES[entity] ?? entity);
}

const TAG = /<(\/?)(b|i|code|pre|blockquote)(?: expandable)?>/g;

export function parse(html: string): TgNode[] {
  const root: TgNode[] = [];
  const stack: { kind: Mark; children: TgNode[] }[] = [];
  const current = () => stack.at(-1)?.children ?? root;
  let last = 0;
  for (const match of html.matchAll(TAG)) {
    const [token, closing, name] = match;
    const index = match.index ?? 0;
    if (index > last) current().push({ kind: "text", text: decode(html.slice(last, index)) });
    last = index + token.length;
    const mark = name as Mark;
    if (!closing) {
      const node = { kind: mark, children: [] as TgNode[] };
      current().push(node);
      stack.push(node);
    } else if (stack.at(-1)?.kind === mark) {
      stack.pop();
    } else {
      current().push({ kind: "text", text: token });
    }
  }
  if (last < html.length) current().push({ kind: "text", text: decode(html.slice(last)) });
  return root;
}

export function plain(nodes: TgNode[]): string {
  return nodes.map((n) => (n.kind === "text" ? n.text : plain(n.children))).join("");
}

export type SectionKind =
  | "header"
  | "data"
  | "portfolio"
  | "changes"
  | "setups"
  | "signals"
  | "market"
  | "narrative"
  | "headlines"
  | "footer"
  | "other";

const SECTION_PREFIXES: [string, SectionKind][] = [
  ["<b>Goldirham Lens</b>", "header"],
  ["Data:", "data"],
  ["<blockquote expandable><b>Data notes</b>", "data"],
  ["<blockquote expandable><b>Headlines</b>", "headlines"],
  ["<b>Portfolio</b>", "portfolio"],
  ["<b>What changed</b>", "changes"],
  ["<b>Setups</b>", "setups"],
  ["<b>Open signals</b>", "signals"],
  ["<b>Market</b>", "market"],
  ["<b>In plain words</b>", "narrative"],
  ["<i>Research and decision support only.", "footer"],
];

export function sectionKind(html: string): SectionKind {
  return SECTION_PREFIXES.find(([prefix]) => html.startsWith(prefix))?.[1] ?? "other";
}

/** Which sections each Telegram message carries. The chunker joins whole sections with a blank line. */
export function groupSections(sections: string[], messages: string[]): number[][] {
  const groups: number[][] = [];
  let next = 0;
  for (const message of messages) {
    const group: number[] = [];
    let joined = "";
    while (next < sections.length && joined !== message) {
      joined = joined ? `${joined}\n\n${sections[next]}` : (sections[next] ?? "");
      group.push(next);
      next += 1;
    }
    if (joined !== message) throw new Error("messages do not rejoin to whole sections");
    groups.push(group);
  }
  return groups;
}
