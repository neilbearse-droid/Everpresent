import Link from "next/link";
import {
  apiFetch,
  type Me,
  type OverviewPayload,
  type TenantSummary,
} from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { TrendChart, HBars } from "@/components/charts";
import { DELTA_DOWN, DELTA_UP, entityColors } from "@/lib/viz";

export default async function OverviewPage() {
  const [me, tenant, overview] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<TenantSummary>("/api/tenant"),
    apiFetch<OverviewPayload>("/api/tenant/overview"),
  ]);

  if (!tenant.data) {
    return (
      <main className="mx-auto max-w-6xl px-8 py-10">
        <DashNav active="Overview" isSuperadmin={me.data?.is_superadmin} />
        <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h2 className="mb-2 text-lg font-medium">No organization selected</h2>
          <p className="text-sm text-slate-400">
            Pick an organization in the switcher above, or ask your EverPresent contact for
            an invite. ({tenant.error})
          </p>
        </section>
      </main>
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

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Overview" isSuperadmin={me.data?.is_superadmin} />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
          <div className="text-3xl font-semibold tabular-nums">
            {data?.latest ? data.latest.brand_score : "—"}
          </div>
          <div className="mt-1 text-sm text-slate-400">
            Brand visibility (0–100){data?.latest ? ` · ${data.latest.date}` : ""}
          </div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
          <div className="text-3xl font-semibold tabular-nums">
            {data && data.brand_name in data.share_of_voice
              ? `${data.share_of_voice[data.brand_name]}%`
              : "—"}
          </div>
          <div className="mt-1 text-sm text-slate-400">Share of voice (30 days)</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
          <div className="text-lg font-medium">{tenant.data.name}</div>
          <div className="mt-1 text-sm text-slate-400">
            {tenant.data.counts.queries} queries · {tenant.data.counts.personas} personas ·{" "}
            {tenant.data.counts.competitors} competitors
          </div>
        </div>
      </div>

      <div className="mb-6 flex gap-3 text-sm">
        <span className="text-slate-500">Export:</span>
        <a href="/dashboard/reports/summary.pdf" className="text-indigo-400 hover:underline">
          Summary PDF
        </a>
        <a href="/dashboard/reports/results.csv" className="text-indigo-400 hover:underline">
          Results CSV
        </a>
        <a href="/dashboard/reports/visibility.csv" className="text-indigo-400 hover:underline">
          Visibility CSV
        </a>
      </div>

      {!hasData ? (
        <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h2 className="mb-2 text-lg font-medium">No measurement data yet</h2>
          <p className="text-sm text-slate-400">
            Visibility appears here after the first completed run.{" "}
            <Link href="/dashboard/runs" className="text-indigo-400 hover:underline">
              See runs →
            </Link>
          </p>
        </section>
      ) : (
        <>
          <section className="mb-6 rounded-lg border border-slate-700 bg-slate-900 p-6">
            <h2 className="mb-4 text-sm font-medium text-slate-400">
              Visibility trend — {data!.brand_name} vs competitors
            </h2>
            <TrendChart data={trendRows} series={trendSeries} />
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
              <h2 className="mb-4 text-sm font-medium text-slate-400">
                Share of voice — mentions across AI answers (30 days)
              </h2>
              <HBars items={sovItems} max={Math.max(...sovItems.map((s) => s.value), 1)} unit="%" />
            </section>

            <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
              <h2 className="mb-4 text-sm font-medium text-slate-400">
                Biggest movers since previous measurement day
              </h2>
              {data!.movers.length === 0 ? (
                <p className="text-sm text-slate-500">
                  Needs two measurement days — trigger another run tomorrow.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data!.movers.map((mover) => (
                    <li
                      key={mover.label}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-slate-300">{mover.label}</span>
                      <span
                        className="tabular-nums"
                        style={{ color: mover.delta >= 0 ? DELTA_UP : DELTA_DOWN }}
                      >
                        {mover.delta >= 0 ? "▲" : "▼"} {mover.delta >= 0 ? "+" : ""}
                        {mover.delta}
                        <span className="ml-2 text-xs text-slate-500">
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
