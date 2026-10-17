import { describe, expect, it } from "vitest";

import { demo } from "@/lib/demo";
import { decode, groupSections, parse, plain, sectionKind } from "@/lib/telegram";

describe("parse", () => {
  it("builds a tree from the renderer's tags and decodes entities", () => {
    expect(parse("<b>KSTL</b> Fear &amp; Greed <i>(Demo)</i>")).toEqual([
      { kind: "b", children: [{ kind: "text", text: "KSTL" }] },
      { kind: "text", text: " Fear & Greed " },
      { kind: "i", children: [{ kind: "text", text: "(Demo)" }] },
    ]);
  });

  it("nests and keeps unknown tags as literal text", () => {
    const nodes = parse("<b>a <code>b</code></b><script>x</script>");
    expect(plain(nodes)).toBe("a b<script>x</script>");
    expect(nodes[0]).toMatchObject({ kind: "b", children: [{ kind: "text" }, { kind: "code" }] });
  });

  it("treats a stray closing tag as text", () => {
    expect(plain(parse("a</i>b"))).toBe("a</i>b");
  });

  it("round-trips every exported section to its visible text", () => {
    for (const day of demo.days) {
      for (const section of day.sections) {
        const text = plain(parse(section));
        expect(text).not.toMatch(/<\/?(b|i|code)>/);
        expect(text).toBe(decode(section.replace(/<\/?(b|i|code)>/g, "")));
      }
    }
  });
});

describe("sections", () => {
  it("names each exported section", () => {
    const kinds = demo.days[1]?.sections.map(sectionKind);
    expect(kinds).toEqual(["header", "data", "portfolio", "changes", "setups", "market", "footer"]);
  });

  it("groups sections into the messages the chunker produced", () => {
    for (const day of demo.days) {
      const groups = groupSections(day.sections, day.messages);
      expect(groups.flat()).toEqual(day.sections.map((_, i) => i));
    }
  });

  it("refuses messages that do not rejoin to whole sections", () => {
    expect(() => groupSections(["a", "b"], ["a\n\nc"])).toThrow();
  });
});
