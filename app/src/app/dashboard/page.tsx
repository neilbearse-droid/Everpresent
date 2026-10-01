import Link from "next/link";
import {
  apiFetch,
  rangeQuery,
  type EngineModesPayload,
  type Me,
  type OverviewPayload,
  type TenantSummary,
} from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { EngineStrip, ModeStack } from "@/components/engine-modes";
import { NoOrgNotice } from "@/components/no-org-notice";
import { TrendChart, HBars } from "@/components/charts";
import { entityColors } from "@/lib/viz";

export default async function OverviewPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, tenant, overview, engineModes] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<TenantSummary>("/api/tenant"),
    apiFetch<OverviewPayload>(`/api/tenant/overview${rangeQuery(from, to)}`),
    apiFetch<EngineModesPayload>(`/api/tenant/engine-modes${rangeQuery(from, to)}`),
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
  const colors = entityColors(data?.brand_name ?? "Brand", competitorNames);

  const trendRows =
    data?.trend.map((point) => ({
      date: point.date,
      [data.brand_name]: point.brand_score,
      ...point.competitors,
    })) ?? [];
  const trendSeries = [data?.brand_name ?? "Brand", ...competitorNames.sort()]
    .filter((name) => colors.has(name))
    .map((name) => ({ name, color: colors.get(name)! }));

  const sovItems = data
    ? Object.entries(data.share_of_voice)
        .sort((a, b) => b[1] - a[1])
        .map(([label, value]) => ({
          label,
          value,
          color: colors.get(label) ?? "#9a9a92",
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
    queries_measured: 0, queries_with_aio: 0, aio_share_pct: 0,
    brand_cited_in_aio: 0, source_types: {},
  };
  const composite = modes?.composite ?? null;

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Overview" isSuperadmin={me.data?.is_superadmin} withDateRange />

      {/* Header block: title cell + export cells. */}
      <section className="blueprint mb-6 grid-cols-1 md:grid-cols-[1fr_auto]">
        <div className="p-5">
          <div className="bp-label mb-2">Overview / engine behaviour in your category</div>
          <h1 className="bp-display">{data?.brand_name ?? tenant.data.name}</h1>
          <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-[var(--text-2)]">
            Each engine builds its answers differently, so each needs a different approach. This
            shows how each one works in your category and where you stand.
          </p>
        </div>
        <div className="bp-stack grid-rows-3">
          {[
            ["Summary", "PDF", "/dashboard/reports/summary.pdf"],
            ["Results", "CSV", "/dashboard/reports/results.csv"],
            ["Visibility", "CSV", "/dashboard/reports/visibility.csv"],
          ].map(([label, fmt, href]) => (
            <a
              key={href}
              href={href}
              className="bp-cell-link flex items-center justify-between gap-6 px-4"
            >
              <span className="bp-label text-[var(--text)]">{label}</span>
              <span className="bp-label">{fmt} ↓</span>
            </a>
          ))}
        </div>
      </section>

      {/* Status bar: the numbers you read first. */}
      <section className="blueprint mb-6 grid-cols-2 md:grid-cols-4">
        <div className="p-3">
          <div className="bp-label">Composite visibility</div>
          <div className="bp-metric bp-critical mt-1 text-[40px]">
            {composite?.score ?? data?.latest?.brand_score ?? "N/A"}
          </div>
        </div>
        <div className="p-3">
          <div className="bp-label">Last measured</div>
          <div className="bp-metric mt-1 text-[22px]">
            {composite?.date ?? data?.latest?.date ?? "Awaiting first run"}
          </div>
        </div>
        <div className="p-3">
          <div className="bp-label">Engines measured</div>
          <div className="bp-metric mt-1 text-[22px]">{modes?.engines.length ?? 0}</div>
        </div>
        <div className="p-3">
          <div className="bp-label">Share-of-voice window</div>
          <div className="bp-metric mt-1 text-[22px]">{sovRangeLabel}</div>
        </div>
      </section>

      {modes?.observed && (
        <section className="mb-6">
          <EngineStrip data={modes} />
        </section>
      )}

      {!hasData ? (
        <section className="blueprint">
          <div className="p-5">
            <h2 className="bp-head mb-2 text-[16px]">No measurement data yet</h2>
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
                <TrendChart data={trendRows} series={trendSeries} />
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
                <HBars items={sovItems} max={Math.max(...sovItems.map((s) => s.value), 1)} unit="%" />
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
                    {data!.movers.filter((m) => m.delta !== 0).map((mover) => (
                      <tr key={mover.label}>
                        <td>{mover.label}</td>
                        <td
                          className={`text-right font-mono font-bold ${mover.delta < 0 ? "bp-neg" : ""}`}
                        >
                          {mover.delta >= 0 ? "▲ +" : "▼ "}
                          {mover.delta}
                        </td>
                        <td className="text-right font-mono">{mover.before}</td>
                        <td className="text-right font-mono">{mover.after}</td>
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
