import { MOTION_ENABLED } from "@/lib/motion-pref";

import { Mark } from "./Mark";
import { MotionToggle } from "./MotionToggle";

export const NAV = [
  { href: "#briefing", label: "Briefing" },
  { href: "#pipeline", label: "How it is made" },
  { href: "#method", label: "Method" },
  { href: "#provenance", label: "Provenance" },
  { href: "#scorecard", label: "Scorecard" },
  { href: "#faq", label: "FAQ" },
];

export function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-rule bg-carbon">
      <div className="shell flex h-14 items-center gap-6">
        <a href="#top" className="flex shrink-0 items-center gap-2.5 no-underline">
          <Mark id="mark-header" className="size-7" />
          <span className="font-display text-xl font-semibold tracking-wide">Goldirham Lens</span>
        </a>
        <nav aria-label="Sections" className="ml-auto hidden lg:block">
          <ul className="flex items-center gap-6 text-sm">
            {NAV.map((item) => (
              <li key={item.href}>
                <a href={item.href} className="text-fog no-underline transition-colors hover:text-paper">
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-3 lg:ml-0">
          {MOTION_ENABLED ? <MotionToggle /> : null}
          <details className="menu relative lg:hidden">
            <summary className="press label flex cursor-pointer list-none items-center gap-2 border border-rule px-3 py-1.5 text-paper [&::-webkit-details-marker]:hidden">
              Menu
            </summary>
            <nav
              aria-label="Sections"
              className="menu-sheet absolute right-0 top-full mt-2 w-60 border border-rule-strong bg-graphite"
            >
              <ul className="divide-y divide-rule">
                {NAV.map((item) => (
                  <li key={item.href}>
                    <a href={item.href} className="block px-4 py-3 text-paper no-underline">
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          </details>
        </div>
      </div>
    </header>
  );
}
