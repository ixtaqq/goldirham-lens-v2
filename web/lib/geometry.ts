// Turns exported series into SVG path data. Coordinates only; no figure is computed here.

export interface Box {
  width: number;
  height: number;
  pad?: number;
}

const round = (value: number) => Math.round(value * 10) / 10;

export function tracePath(values: number[], { width, height, pad = 0 }: Box): string {
  if (values.length === 0) return "";
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  return values
    .map((value, index) => {
      const x = round(index * step);
      const y = round(pad + (1 - value) * (height - 2 * pad));
      return `${index === 0 ? "M" : "L"}${x} ${y}`;
    })
    .join(" ");
}

export interface Scale {
  min: number;
  max: number;
  y: (value: number) => number;
}

export function linearScale(values: number[], { height, pad = 0 }: Box): Scale {
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const span = max - min || 1;
  return { min, max, y: (value) => round(pad + ((max - value) / span) * (height - 2 * pad)) };
}

export function stepPath(values: number[], box: Box): { d: string; zero: number } {
  const scale = linearScale(values, box);
  if (values.length === 0) return { d: "", zero: scale.y(0) };
  const step = box.width / values.length;
  let d = `M0 ${scale.y(0)}`;
  values.forEach((value, index) => {
    const x = round((index + 1) * step);
    d += ` H${x} V${scale.y(value)}`;
  });
  return { d, zero: scale.y(0) };
}
