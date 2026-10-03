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
import { SERIES_DASHES } from "@/lib/viz";

// Recessive gridlines: softer than the card hairline so the data reads first.
const GRID = "var(--line)";
const AXIS_LINE = "var(--line)";
const AXIS_TEXT = "var(--text)";
const MONO = "Geist Mono, ui-monospace, monospace";

/** Dash pattern for a series by its slot (brand first, then competitors in
 * the same order entityColors assigns), so same-grey competitors stay
 * distinguishable. */
function dashFor(index: number): string {
  return SERIES_DASHES[index % SERIES_DASHES.length];
}

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
            <span key={s.name} className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-2)]">
              <svg width="22" height="8" aria-hidden>
                <line
                  x1="0" y1="4" x2="22" y2="4"
                  stroke={s.color}
                  strokeWidth={s === series[0] ? 4 : 2}
                  strokeDasharray={dashFor(series.indexOf(s))}
                />
              </svg>
              {s.name}
            </span>
          ))}
        </div>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeOpacity={0.18} strokeDasharray="2 4" />
          <XAxis
            dataKey="date"
            tick={{ fill: AXIS_TEXT, fontSize: 10.5, fontFamily: MONO }}
            axisLine={{ stroke: AXIS_LINE, strokeWidth: 1 }}
            tickLine={false}
            dy={4}
          />
          <YAxis
            domain={[0, 100]}
            width={34}
            tick={{ fill: AXIS_TEXT, fontSize: 10.5, fontFamily: MONO }}
            axisLine={{ stroke: AXIS_LINE, strokeWidth: 1 }}
            tickLine={false}
          />
          <Tooltip
            cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              fontSize: 12,
              fontFamily: MONO,
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
              type="linear"
              dataKey={s.name}
              stroke={s.color}
              // The brand (first series) is the heavy accent line.
              strokeWidth={seriesIndex === 0 ? 2.5 : 1.5}
              strokeDasharray={dashFor(seriesIndex)}
              dot={(props: { index?: number; cx?: number; cy?: number }) =>
                props.index === last && props.cx != null && props.cy != null ? (
                  <circle
                    key={`${s.name}-end`}
                    cx={props.cx}
                    cy={props.cy}
                    r={4}
                    fill={s.color}
                    stroke="var(--surface)"
                    strokeWidth={2}
                  />
                ) : (
                  <g key={`${s.name}-${props.index}`} />
                )
              }
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal labeled bars in plain HTML: thin square-ended marks,
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
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.label} className="group" title={`${item.label}: ${item.value}${unit}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="flex min-w-0 items-center gap-1.5 text-[12px] font-medium text-[var(--text-2)]">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 border border-[var(--line)]"
                style={{ background: item.color }}
              />
              <span className="truncate">{item.label}</span>
            </span>
            <span className="font-semibold tabular-nums text-[var(--text)]">
              {item.value}
              {unit}
            </span>
          </div>
          <div className="h-3 w-full border-[1.5px] border-[var(--line)] bg-[var(--surface)]">
            <div
              className="h-full border-r-[1.5px] border-[var(--line)] group-hover:opacity-80"
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
