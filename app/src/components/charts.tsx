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

const GRID = "rgba(255,255,255,0.07)"; // recessive hairline on the dark surface
const AXIS_TEXT = "#8b93a3";

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
            <span key={s.name} className="flex items-center gap-1.5 text-xs text-slate-300">
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
            axisLine={{ stroke: GRID }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            width={34}
            tick={{ fill: AXIS_TEXT, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ stroke: AXIS_TEXT, strokeWidth: 1 }}
            contentStyle={{
              background: "#15171d",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: 10,
              fontSize: 12,
              boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
            }}
            labelStyle={{ color: "#f3f5fa" }}
            formatter={(value: number | string, name: string) => [value, name]}
          />
          {series.map((s, seriesIndex) => (
            <Line
              key={s.name}
              type="monotone"
              dataKey={s.name}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
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
    return <p className="text-sm text-slate-500">No data yet.</p>;
  }
  return (
    <ul className="space-y-2.5">
      {items.map((item) => (
        <li key={item.label} className="group" title={`${item.label}: ${item.value}${unit}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="flex min-w-0 items-center gap-1.5 text-slate-300">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: item.color }}
              />
              <span className="truncate">{item.label}</span>
            </span>
            <span className="tabular-nums text-slate-200">
              {item.value}
              {unit}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-white/[0.06]">
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
