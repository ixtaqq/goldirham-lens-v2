// One stroke weight, one 12-unit grid. Decorative unless a label is given.

type IconProps = { className?: string };

const base = { viewBox: "0 0 12 12", "aria-hidden": true, fill: "none", stroke: "currentColor", strokeWidth: 1.6 } as const;

export function Check({ className = "size-3" }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M2 6.5 L5 9 L10 3" />
    </svg>
  );
}

export function Cross({ className = "size-3" }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M3 3 L9 9 M9 3 L3 9" />
    </svg>
  );
}

export function Dash({ className = "size-3" }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M2 6 H10" />
    </svg>
  );
}
