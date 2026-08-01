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
import { EngineModesHero } from "@/components/engine-modes";
import { NoOrgNotice } from "@/components/no-org-notice";
import { TrendChart, HBars } from "@/components/charts";
import { DELTA_DOWN, DELTA_UP, entityColors } from "@/lib/viz";

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
          color: colors.get(label) ?? "#64748b",
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

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Overview" isSuperadmin={me.data?.is_superadmin} withDateRange />

      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-1.5">How each engine answers your category</p>
          <h1 className="text-[26px] font-semibold tracking-tight">
            {data?.brand_name ?? tenant.data.name}
          </h1>
          <p className="mt-1 max-w-xl text-[13px] text-[var(--text-2)]">
            Visibility isn&apos;t one number. Each engine reaches its answer differently in your
            category — so the tactic is different too. Here&apos;s how, and where you stand in each.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[13px]">
          <a href="/dashboard/reports/summary.pdf" className="btn btn-ghost px-3 py-1.5">
            Summary PDF
          </a>
          <a href="/dashboard/reports/results.csv" className="btn btn-ghost px-3 py-1.5">
            Results CSV
          </a>
          <a href="/dashboard/reports/visibility.csv" className="btn btn-ghost px-3 py-1.5">
            Visibility CSV
          </a>
        </div>
      </div>

      {engineModes.data?.observed ? (
        <div className="mb-6">
          <EngineModesHero
            data={engineModes.data}
            aio={data?.aio ?? {
              queries_measured: 0, queries_with_aio: 0, aio_share_pct: 0,
              brand_cited_in_aio: 0, source_types: {},
            }}
          />
        </div>
      ) : (
        <div className="mb-6 card p-5">
          <p className="eyebrow mb-2.5">Brand visibility</p>
          <div className="flex items-baseline gap-1.5">
            <span className="text-4xl font-semibold leading-none tabular-nums">
              {data?.latest ? data.latest.brand_score : "—"}
            </span>
            <span className="text-base text-[var(--text-3)]">/100</span>
          </div>
          <p className="mt-2.5 text-xs text-[var(--text-3)]">
            {data?.latest
              ? `Latest measurement · ${data.latest.date} · per-engine breakdown appears after the next run`
              : "Awaiting first run"}
          </p>
        </div>
      )}

      {!hasData ? (
        <section className="card p-6">
          <h2 className="mb-2 text-lg font-medium">No measurement data yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Visibility appears here after the first completed run.{" "}
            <Link href="/dashboard/runs" className="text-[var(--accent)] hover:underline">
              See runs →
            </Link>
          </p>
        </section>
      ) : (
        <>
          <section className="mb-6 card p-6">
            <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
              Visibility trend — {data!.brand_name} vs competitors
            </h2>
            <TrendChart data={trendRows} series={trendSeries} />
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="card p-6">
              <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
                Share of voice — mentions across AI answers ({sovRangeLabel})
              </h2>
              <HBars items={sovItems} max={Math.max(...sovItems.map((s) => s.value), 1)} unit="%" />
            </section>

            <section className="card p-6">
              <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
                Biggest movers since previous measurement day
              </h2>
              {data!.movers.length === 0 ? (
                <p className="text-sm text-[var(--text-3)]">
                  Needs two measurement days — trigger another run tomorrow.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data!.movers.map((mover) => (
                    <li
                      key={mover.label}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-[var(--text-2)]">{mover.label}</span>
                      <span
                        className="tabular-nums"
                        style={{ color: mover.delta >= 0 ? DELTA_UP : DELTA_DOWN }}
                      >
                        {mover.delta >= 0 ? "▲" : "▼"} {mover.delta >= 0 ? "+" : ""}
                        {mover.delta}
                        <span className="ml-2 text-xs text-[var(--text-3)]">
                          {mover.before} → {mover.after}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </main>
  );
}
