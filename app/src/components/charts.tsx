"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Recessive gridlines: softer than the card hairline so the data reads first.
const GRID = "color-mix(in srgb, var(--text) 8%, transparent)";
const AXIS_LINE = "color-mix(in srgb, var(--text) 12%, transparent)";
const AXIS_TEXT = "var(--text-3)";

type TrendRow = Record<string, string | number>;

export function TrendChart({
  data,
  series,
}: {
  data: TrendRow[];
  series: { name: string; color: string }[];
}) {
  const last = data.length - 1;
  return (
    <div>
      {/* Legend always present for ≥2 series; chips carry color, text stays in
          text tokens. */}
      {series.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1">
          {series.map((s) => (
            <span key={s.name} className="flex items-center gap-1.5 text-xs text-[var(--text-2)]">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: s.color }}
              />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 110, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="0" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: AXIS_TEXT, fontSize: 11 }}
            axisLine={{ stroke: AXIS_LINE }}
            tickLine={false}
            dy={4}
          />
          <YAxis
            domain={[0, 100]}
            width={34}
            tick={{ fill: AXIS_TEXT, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ stroke: AXIS_LINE, strokeWidth: 1 }}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              fontSize: 12,
              boxShadow: "var(--shadow-3)",
              color: "var(--text)",
              padding: "8px 12px",
            }}
            labelStyle={{ color: "var(--text)", fontWeight: 600, marginBottom: 2 }}
            itemStyle={{ color: "var(--text-2)" }}
            formatter={(value: number | string, name: string) => [value, name]}
          />
          {series.map((s, seriesIndex) => (
            <Line
              key={s.name}
              type="monotone"
              dataKey={s.name}
              stroke={s.color}
              strokeWidth={2.25}
              strokeLinecap="round"
              strokeLinejoin="round"
              // Emphasised endpoint: a filled dot ringed in the surface colour
              // at the latest measurement, so the current value reads first.
              dot={(props: { index?: number; cx?: number; cy?: number }) =>
                props.index === last && props.cx != null && props.cy != null ? (
                  <circle
                    key={`${s.name}-end`}
                    cx={props.cx}
                    cy={props.cy}
                    r={3.5}
                    fill={s.color}
                    stroke="var(--surface)"
                    strokeWidth={2}
                  />
                ) : (
                  <g key={`${s.name}-${props.index}`} />
                )
              }
              activeDot={{ r: 4.5, strokeWidth: 2, stroke: "var(--surface)" }}
              isAnimationActive={false}
              // Selective direct label at the line end (secondary encoding on
              // top of the legend), staggered a little per series.
              label={(props: { index?: number; x?: number; y?: number; value?: number }) =>
                props.index === last && props.x != null && props.y != null ? (
                  <text
                    x={props.x + 8}
                    y={props.y + (seriesIndex % 3) * 4 - 4}
                    fill={AXIS_TEXT}
                    fontSize={11}
                  >
                    {shortName(s.name)}
                  </text>
                ) : (
                  <g />
                )
              }
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function shortName(name: string): string {
  return name.length > 16 ? name.slice(0, 15) + "…" : name;
}

/** Horizontal labeled bars in plain HTML: thin marks, rounded data end,
 * per-row hover, values in text tokens. Max is 100 for scores, or the data
 * max for shares. */
export function HBars({
  items,
  max = 100,
  unit = "",
}: {
  items: { label: string; value: number; color: string }[];
  max?: number;
  unit?: string;
}) {
  if (items.length === 0) {
    return <p className="text-sm text-[var(--text-3)]">No data yet.</p>;
  }
  return (
    <ul className="space-y-2.5">
      {items.map((item) => (
        <li key={item.label} className="group" title={`${item.label}: ${item.value}${unit}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="flex min-w-0 items-center gap-1.5 text-[var(--text-2)]">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: item.color }}
              />
              <span className="truncate">{item.label}</span>
            </span>
            <span className="tabular-nums text-[var(--text)]">
              {item.value}
              {unit}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-[color-mix(in_srgb,var(--text)_9%,transparent)]">
            <div
              className="h-2 rounded-full transition-opacity group-hover:opacity-80"
              style={{
                width: `${Math.min(100, (item.value / max) * 100)}%`,
                background: item.color,
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
