/** A balance-style area sparkline: the brand's line in the accent over a
 * soft fill, three hairline gridlines, no axes. Server-rendered SVG. */
export function Sparkline({
  values,
  height = 132,
  label,
}: {
  values: number[];
  height?: number;
  label: string;
}) {
  if (values.length < 2) {
    return (
      <div
        className="grid place-items-center text-xs text-[var(--text-3)]"
        style={{ height }}
      >
        The trend appears after two runs.
      </div>
    );
  }
  const w = 600;
  const pad = 6;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const x = (i: number) => (i / (values.length - 1)) * w;
  const y = (v: number) => pad + (1 - (v - lo) / span) * (height - pad * 2);
  const line = values
    .map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    .join("");
  const area = `${line}L${w},${height}L0,${height}Z`;
  const last = values[values.length - 1];
  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      className="block w-full"
      style={{ height }}
      role="img"
      aria-label={label}
    >
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.18" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => (
        <line
          key={f}
          x1="0"
          x2={w}
          y1={height * f}
          y2={height * f}
          stroke="var(--line)"
          strokeDasharray="3 4"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      <path d={area} fill="url(#spark-fill)" />
      <path
        d={line}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={x(values.length - 1)}
        cy={y(last)}
        r="3.5"
        fill="var(--surface)"
        stroke="var(--accent)"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
