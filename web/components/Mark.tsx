// The brand mark: a square verification frame crossed by a stepped trace. The part of the trace
// inside the frame is mint, because that is where the data was checked.

const TRACE = "M4 96 H24 V80 H40 V86 H54 V60 H70 V48 H84 V30 H116";
const FRAME = { x: 46, y: 22, size: 52 };

export function Mark({ id, className, title }: { id: string; className?: string; title?: string }) {
  const clip = `${id}-clip`;
  return (
    <svg
      viewBox="0 0 120 120"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      fill="none"
    >
      <defs>
        <clipPath id={clip}>
          <rect x={FRAME.x} y={FRAME.y} width={FRAME.size} height={FRAME.size} />
        </clipPath>
      </defs>
      <rect
        className="mark-frame"
        pathLength={1}
        x={FRAME.x}
        y={FRAME.y}
        width={FRAME.size}
        height={FRAME.size}
        stroke="var(--color-paper)"
        strokeWidth={2}
      />
      <path
        className="mark-trace"
        pathLength={1}
        d={TRACE}
        stroke="var(--color-fog)"
        strokeWidth={3}
        strokeLinejoin="miter"
      />
      <path
        className="mark-trace-verified"
        pathLength={1}
        d={TRACE}
        clipPath={`url(#${clip})`}
        stroke="var(--color-mint)"
        strokeWidth={3}
        strokeLinejoin="miter"
      />
    </svg>
  );
}
