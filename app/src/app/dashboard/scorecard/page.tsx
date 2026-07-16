import { apiFetch, type KpiScorecard, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { HBars } from "@/components/charts";
import { entityColors, surfaceLabel } from "@/lib/viz";

const STABILITY_STYLE: Record<string, string> = {
  Stable: "text-emerald-400",
  "Some volatility": "text-amber-400",
  Volatile: "text-red-400",
  "Not enough history": "text-slate-500",
};

function Tile({ value, label, sub }: { value: string; label: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-sm text-slate-400">{label}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export default async function ScorecardPage() {
  const [me, sc] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<KpiScorecard>("/api/tenant/kpi-scorecard"),
  ]);
  if (sc.status === 403) {
    return <NoOrgNotice active="Scorecard" isSuperadmin={me.data?.is_superadmin} detail={sc.error} />;
  }
  const d = sc.data;
  if (!d || d.prominence.measured === 0) {
    return (
      <main className="mx-auto max-w-6xl px-8 py-10">
        <DashNav active="Scorecard" isSuperadmin={me.data?.is_superadmin} />
        <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h2 className="mb-2 text-lg font-medium">No scorecard yet</h2>
          <p className="text-sm text-slate-400">
            The KPI scorecard appears after a completed run.
          </p>
        </section>
      </main>
    );
  }

  const colors = entityColors(d.brand_name, d.share_breakdown.map((s) => s.name).filter((n) => n !== d.brand_name));
  const shareItems = d.share_breakdown.map((s) => ({
    label: s.name,
    value: s.share,
    color: colors.get(s.name) ?? "#64748b",
  }));
  const pd = d.prominence.position_distribution;
  const maxRate = Math.max(...d.stability.series.map((s) => s.presence_rate), 1);

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Scorecard" isSuperadmin={me.data?.is_superadmin} />

      {/* North-star */}
      <section className="mb-6 rounded-lg border border-indigo-500/40 bg-indigo-500/5 p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-slate-400">
              Answer Share — {d.brand_name}
            </div>
            <div className="mt-1 text-5xl font-semibold tabular-nums">{d.answer_share}%</div>
            <p className="mt-1 max-w-md text-xs text-slate-500">
              Your prominence-weighted share of the AI answer vs competitors — earlier and
              more often named counts for more. The one number that isn't a vanity metric.
            </p>
          </div>
          <div className="min-w-64 flex-1">
            <HBars items={shareItems} max={Math.max(...shareItems.map((s) => s.value), 1)} unit="%" />
          </div>
        </div>
      </section>

      {/* Reach + Durability tiles */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          value={`${d.prominence.presence_rate}%`}
          label="Presence rate"
          sub={`${d.prominence.present}/${d.prominence.measured} queries`}
        />
        <Tile
          value={`${d.prominence.lead_rate}%`}
          label="Lead rate — first name in the answer"
          sub="of queries where you appear"
        />
        <Tile
          value={d.prominence.avg_rank === null ? "—" : `#${d.prominence.avg_rank}`}
          label="Average position when named"
        />
        <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
          <div className={`text-3xl font-semibold ${STABILITY_STYLE[d.stability.label] ?? ""}`}>
            {d.stability.label}
          </div>
          <div className="mt-1 text-sm text-slate-400">Stability</div>
          <div className="text-xs text-slate-500">
            {d.stability.swing}pt swing over {d.stability.series.length} runs
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Prominence distribution */}
        <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h2 className="mb-4 text-sm font-medium text-slate-400">
            Prominence — where you land when named
          </h2>
          <HBars
            items={[
              { label: "Leads the answer (1st)", value: pd.leads, color: "#34d399" },
              { label: "Second", value: pd.second, color: "#60a5fa" },
              { label: "Third or later", value: pd.third_plus, color: "#94a3b8" },
            ]}
            max={Math.max(pd.leads, pd.second, pd.third_plus, 1)}
          />
          <p className="mt-3 text-xs text-slate-500">
            Being <em>named</em> isn't the same as being <em>recommended</em>. Leading the
            answer is what moves buyers.
          </p>
        </section>

        {/* Sentiment / framing */}
        <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h2 className="mb-4 text-sm font-medium text-slate-400">
            Framing — how you're described
          </h2>
          <div className="mb-4 flex gap-4 text-sm">
            <span className="text-emerald-400">▲ {d.sentiment.counts.positive} positive</span>
            <span className="text-slate-400">● {d.sentiment.counts.neutral} neutral</span>
            <span className="text-red-400">▼ {d.sentiment.counts.negative} negative</span>
          </div>
          {[...d.sentiment.examples.negative, ...d.sentiment.examples.positive]
            .slice(0, 3)
            .map((ex, i) => (
              <blockquote key={i} className="mb-2 border-l-2 border-slate-700 pl-3 text-xs text-slate-400">
                "{ex.snippet}"
                <span className="mt-0.5 block text-slate-600">
                  {ex.query} · {surfaceLabel(ex.surface)}
                </span>
              </blockquote>
            ))}
          {d.sentiment.counts.positive + d.sentiment.counts.negative === 0 && (
            <p className="text-xs text-slate-500">Mostly neutral framing so far.</p>
          )}
        </section>
      </div>

      {/* Head-to-head */}
      <section className="mt-6 rounded-lg border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-1 text-sm font-medium text-slate-400">
          Head-to-head — when you both appear, who leads
        </h2>
        <p className="mb-4 text-xs text-slate-500">
          On queries where you and a rival are both named, how often you're named first.
        </p>
        {d.head_to_head.length === 0 ? (
          <p className="text-sm text-slate-500">No shared appearances yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-slate-400">
              <tr>
                <th className="py-2 pr-4">Competitor</th>
                <th className="pr-4">Shared queries</th>
                <th className="pr-4">You lead</th>
                <th>Win rate</th>
              </tr>
            </thead>
            <tbody>
              {d.head_to_head.map((h) => (
                <tr key={h.competitor} className="border-t border-slate-800">
                  <td className="py-2 pr-4">{h.competitor}</td>
                  <td className="pr-4 tabular-nums">{h.shared}</td>
                  <td className="pr-4 tabular-nums">{h.wins}</td>
                  <td
                    className={`tabular-nums ${h.win_rate >= 50 ? "text-emerald-400" : "text-amber-400"}`}
                  >
                    {h.win_rate}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {d.stability.series.length >= 2 && (
        <section className="mt-6 rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h2 className="mb-4 text-sm font-medium text-slate-400">
            Presence rate over recent runs (durability)
          </h2>
          <div className="flex items-end gap-2" style={{ height: 120 }}>
            {d.stability.series.map((s) => (
              <div key={s.run_id} className="flex flex-1 flex-col items-center gap-1">
                <div
                  className="w-full rounded-t bg-indigo-500"
                  style={{ height: `${(s.presence_rate / maxRate) * 100}%`, minHeight: 2 }}
                  title={`Run #${s.run_id}: ${s.presence_rate}%`}
                />
                <span className="text-[10px] text-slate-500">#{s.run_id}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
