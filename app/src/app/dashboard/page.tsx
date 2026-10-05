import Link from "next/link";
import {
  apiFetch,
  rangeQuery,
  type Briefing,
  type EngineModesPayload,
  type Me,
  type OverviewPayload,
  type TenantSummary,
} from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { EngineStrip, ModeStack } from "@/components/engine-modes";
import { NoOrgNotice } from "@/components/no-org-notice";
import { TrendChart, HBars } from "@/components/charts";
import { entityColors, fmtDate, OTHER_COLOR } from "@/lib/viz";
import { Sparkline } from "@/components/sparkline";
import { BriefingBlock } from "./briefing";

export default async function OverviewPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, tenant, overview, engineModes, briefing] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<TenantSummary>("/api/tenant"),
    apiFetch<OverviewPayload>(`/api/tenant/overview${rangeQuery(from, to)}`),
    apiFetch<EngineModesPayload>(
      `/api/tenant/engine-modes${rangeQuery(from, to)}`,
    ),
    apiFetch<Briefing>("/api/tenant/briefing"),
  ]);

  if (!tenant.data) {
    return (
      <NoOrgNotice
        active="Overview"
        isSuperadmin={me.data?.is_superadmin}
        detail={tenant.error}
      />
    );
  }

  const data = overview.data;
  const competitorNames = data
    ? [...new Set(data.trend.flatMap((t) => Object.keys(t.competitors)))]
    : [];
  // Rank rivals by share of voice so the chart shows the ones that matter.
  const shareOf = (name: string) => data?.share_of_voice[name] ?? 0;
  const rivalsByShare = [...competitorNames].sort(
    (a, b) => shareOf(b) - shareOf(a) || a.localeCompare(b),
  );
  const colors = entityColors(data?.brand_name ?? "Brand", rivalsByShare);

  const trendRows =
    data?.trend.map((point) => ({
      date: point.date,
      [data.brand_name]: point.brand_score,
      ...point.competitors,
    })) ?? [];
  const trendSeries = [data?.brand_name ?? "Brand", ...rivalsByShare]
    .filter((name) => colors.has(name))
    .map((name) => ({ name, color: colors.get(name)! }));

  const sovItems = data
    ? Object.entries(data.share_of_voice)
        .sort((a, b) => b[1] - a[1])
        .map(([label, value]) => ({
          label,
          value,
          color: colors.get(label) ?? OTHER_COLOR,
        }))
    : [];

  const hasData = trendRows.length > 0;

  // Share-of-voice honours the picked range; the label must follow it rather
  // than always claiming "30 days" (the trailing default only applies when no
  // range is set).
  const sovRangeLabel =
    from && to
      ? `${from} → ${to}`
      : from
        ? `since ${from}`
        : to
          ? `through ${to}`
          : "last 30 days";

  const modes = engineModes.data;
  const aio = data?.aio ?? {
    queries_measured: 0,
    queries_with_aio: 0,
    aio_share_pct: 0,
    brand_cited_in_aio: 0,
    source_types: {},
  };
  const composite = modes?.composite ?? null;
  const mr = data?.mention_rate;

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav
        active="Overview"
        isSuperadmin={me.data?.is_superadmin}
        withDateRange
      />

      {/* Hero: the account balance of AI visibility. */}
      <section className="card mb-6 overflow-hidden">
        <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <div className="p-6">
            <div className="flex flex-wrap items-center gap-2">
              <span className="bp-label">
                {data?.brand_name ?? tenant.data.name} · Named in AI answers
              </span>
              {mr && mr.answers > 0 && (
                <span
                  className={`pill ${
                    mr.change.verdict === "up"
                      ? "pill-good"
                      : mr.change.verdict === "down"
                        ? "pill-bad"
                        : ""
                  }`}
                >
                  {mr.change.verdict === "up"
                    ? `Gaining +${mr.change.delta} pts`
                    : mr.change.verdict === "down"
                      ? `Losing ${mr.change.delta} pts`
                      : mr.change.verdict === "no real change"
                        ? "Holding steady"
                        : "Building baseline"}
                </span>
              )}
            </div>
            <div className="ep-hero-figure mt-4">
              {mr && mr.answers > 0 ? (
                <>
                  {mr.rate}
                  <small>%</small>
                </>
              ) : (
                "—"
              )}
            </div>
            <p className="mt-3 text-[13px] text-[var(--text-2)]">
              {mr && mr.answers > 0
                ? `95% range ${mr.low}–${mr.high}% across ${mr.answers.toLocaleString()} answers`
                : "Awaiting the first run"}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {[
                ["Client report (PDF)", "/dashboard/reports/summary.pdf"],
                ["Data workbook (Excel)", "/dashboard/reports/report.xlsx"],
                ["Results CSV", "/dashboard/reports/results.csv"],
                ["Visibility CSV", "/dashboard/reports/visibility.csv"],
              ].map(([label, href]) => (
                <a
                  key={href}
                  href={href}
                  className="btn btn-ghost px-3 text-[12.5px]"
                >
                  {label} <span aria-hidden>↓</span>
                </a>
              ))}
            </div>
          </div>
          <div className="border-t border-[var(--line)] p-6 md:border-l md:border-t-0">
            <div className="flex items-baseline justify-between">
              <span className="bp-label">Visibility score</span>
              <span className="text-xs text-[var(--text-3)]">
                {trendRows.length > 0
                  ? `${fmtDate(trendRows[0].date)} – ${fmtDate(trendRows[trendRows.length - 1].date)}`
                  : ""}
              </span>
            </div>
            <div className="mt-4">
              <Sparkline
                values={(data?.trend ?? []).map((t) => t.brand_score)}
                label="Brand visibility score over time"
              />
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-px border-t border-[var(--line)] bg-[var(--line)] md:grid-cols-4 [&>*]:bg-[var(--surface)]">
          <div className="px-6 py-4">
            <div className="bp-label">Composite visibility</div>
            <div className="bp-metric mt-1.5 text-[26px] text-[var(--accent-display)]">
              {composite?.score ?? data?.latest?.brand_score ?? "—"}
            </div>
          </div>
          <div className="px-6 py-4">
            <div className="bp-label">Share of voice</div>
            <div className="bp-metric mt-1.5 text-[26px]">
              {data && data.share_of_voice[data.brand_name] !== undefined
                ? `${data.share_of_voice[data.brand_name]}%`
                : "—"}
            </div>
            <div className="text-[11px] text-[var(--text-3)]">
              {sovRangeLabel}
            </div>
          </div>
          <div className="px-6 py-4">
            <div className="bp-label">Top rival</div>
            <div className="mt-1.5 truncate text-[17px] font-semibold tracking-[-0.02em]">
              {rivalsByShare[0] ?? "—"}
            </div>
            {rivalsByShare[0] && (
              <div className="text-[11px] tabular-nums text-[var(--text-3)]">
                {shareOf(rivalsByShare[0])}% share of voice
              </div>
            )}
          </div>
          <div className="px-6 py-4">
            <div className="bp-label">Last measured</div>
            <div className="mt-1.5 text-[17px] font-semibold tracking-[-0.02em]">
              {fmtDate(composite?.date ?? data?.latest?.date) ||
                "Awaiting first run"}
            </div>
          </div>
        </div>
      </section>

      {briefing.data && <BriefingBlock b={briefing.data} />}

      {(data?.alerts?.length ?? 0) > 0 && (
        <section className="blueprint mb-6 grid-cols-1">
          <div>
            <div className="bp-bar">
              <span>What changed</span>
              <span>{data!.alerts!.length}</span>
            </div>
            <ul>
              {data!.alerts!.map((a, i) => (
                <li
                  key={i}
                  className="flex items-start gap-3 border-t border-[var(--line)] px-4 py-2.5 text-[13px] first:border-t-0"
                >
                  <span
                    className={`bp-label shrink-0 px-1.5 ${
                      a.severity === "high"
                        ? "bp-neg"
                        : a.severity === "good"
                          ? "bp-mark"
                          : ""
                    }`}
                  >
                    {a.severity === "high"
                      ? "Act"
                      : a.severity === "good"
                        ? "Win"
                        : "Watch"}
                  </span>
                  <span className="text-[var(--text)]">{a.text}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {modes?.observed && (
        <section className="mb-6">
          <EngineStrip data={modes} />
        </section>
      )}

      {!hasData ? (
        <section className="blueprint">
          <div className="p-5">
            <h2 className="bp-head mb-2 text-[16px]">
              No measurement data yet
            </h2>
            <p className="text-sm text-[var(--text-2)]">
              Visibility appears here after the first completed run.{" "}
              <Link href="/dashboard/runs" className="bp-link">
                See runs →
              </Link>
            </p>
          </div>
        </section>
      ) : (
        <>
          {/* Asymmetric row: trend (8) + mode stack (4). */}
          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-12">
            <div className="lg:col-span-8">
              <div className="bp-bar">
                <span>Visibility trend</span>
                <span>Score 0–100</span>
              </div>
              <div className="p-4">
                {trendRows.length >= 2 ? (
                  <TrendChart data={trendRows} series={trendSeries} />
                ) : (
                  <p className="py-16 text-center text-sm text-[var(--text-3)]">
                    The trend line appears after a second day of measurements.
                  </p>
                )}
                {(data?.series_notes ?? []).map((n) => (
                  <p
                    key={`${n.surface}-${n.date}`}
                    className="mt-2 text-xs text-[var(--text-3)]"
                  >
                    <span className="bp-label">Series break · {n.date}</span>{" "}
                    {n.note}
                  </p>
                ))}
              </div>
            </div>
            <div className="bp-stack lg:col-span-4">
              {modes?.observed ? (
                <ModeStack data={modes} aio={aio} />
              ) : (
                <div className="p-3 text-sm text-[var(--text-2)]">
                  Per-engine breakdown appears after the next run.
                </div>
              )}
            </div>
          </section>

          {/* Asymmetric row: share of voice (7) + movers table (5). */}
          <section className="blueprint grid-cols-1 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <div className="bp-bar">
                <span>Share of voice</span>
                <span>{sovRangeLabel}</span>
              </div>
              <div className="p-4">
                <HBars
                  items={sovItems}
                  max={Math.max(...sovItems.map((s) => s.value), 1)}
                  unit="%"
                />
              </div>
            </div>
            <div className="lg:col-span-5">
              <div className="bp-bar">
                <span>Biggest movers</span>
                <span>vs previous day</span>
              </div>
              {data!.movers.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">
                  Available after a second day of measurement.
                </p>
              ) : data!.movers.every((m) => m.delta === 0) ? (
                <p className="p-4 text-sm text-[var(--text-2)]">
                  No change since the previous measurement.
                </p>
              ) : (
                <table className="bp-table w-full">
                  <thead>
                    <tr>
                      <th>Entity</th>
                      <th className="text-right">Δ</th>
                      <th className="text-right">Before</th>
                      <th className="text-right">After</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data!.movers
                      .filter((m) => m.delta !== 0)
                      .map((mover) => (
                        <tr key={mover.label}>
                          <td>{mover.label}</td>
                          <td
                            className={`text-right font-mono font-bold ${mover.delta < 0 ? "bp-neg" : ""}`}
                          >
                            {mover.delta >= 0 ? "▲ +" : "▼ "}
                            {mover.delta}
                          </td>
                          <td className="text-right font-mono">
                            {mover.before}
                          </td>
                          <td className="text-right font-mono">
                            {mover.after}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
