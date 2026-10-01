import {
  apiFetch,
  rangeQuery,
  type AccuracyReport,
  type KpiScorecard,
  type Me,
  type MentionRates,
  type RateChange,
} from "@/lib/api";
import { GenerateDraft } from "./generate-draft";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { HBars } from "@/components/charts";
import { entityColors, surfaceLabel } from "@/lib/viz";

const STABILITY_STYLE: Record<string, string> = {
  Stable: "text-[var(--pos)]",
  "Some volatility": "text-[var(--warn-t)]",
  Volatile: "text-[var(--neg)]",
  "Not enough history": "text-[var(--text-3)]",
};

function Tile({ value, label, sub }: { value: string; label: string; sub?: string }) {
  return (
    <div className="card p-4">
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-sm text-[var(--text-2)]">{label}</div>
      {sub && <div className="text-xs text-[var(--text-3)]">{sub}</div>}
    </div>
  );
}

function ChangeBadge({ change }: { change: RateChange }) {
  if (change.verdict === "up" || change.verdict === "down") {
    const up = change.verdict === "up";
    return (
      <span className={`chip ${up ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
        {up ? "▲" : "▼"} {change.delta! > 0 ? "+" : ""}
        {change.delta}pt · real change
      </span>
    );
  }
  return (
    <span className="chip text-[var(--text-3)]">
      {change.verdict === "no real change" ? "no real change" : "not enough data yet"}
    </span>
  );
}

/** The headline: how often AI answers name you, with an honest range. Answers
 * vary run to run, so a single reading is noise; the pooled rate isn't. */
function MentionRatePanel({ m, brand }: { m: MentionRates; brand: string }) {
  const o = m.overall;
  return (
    <section className="card mb-6 p-4">
      <div className="flex flex-wrap items-start justify-between gap-10">
        <div>
          <p className="eyebrow mb-2">Mention rate · {brand}</p>
          <div className="flex items-baseline gap-3">
            <span className="text-6xl font-semibold leading-none tabular-nums text-[var(--text)]">
              {o.rate}%
            </span>
            <span className="text-lg tabular-nums text-[var(--text-2)]">
              ({o.low}–{o.high}%)
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <ChangeBadge change={o.change} />
            <span className="text-[var(--text-3)]">
              {o.answers} answers · {o.prompts} prompts · {m.window.start} to {m.window.end}
            </span>
          </div>
          <p className="mt-3 max-w-md text-xs leading-relaxed text-[var(--text-3)]">
            How often AI answers name you, across every run in the window. The range is the 95%
            confidence interval. A change is flagged only when the second half of the window
            differs from the first by more than the noise.
          </p>
        </div>
        <div className="min-w-72 flex-1 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs text-[var(--text-3)]">
                <th className="pb-2 pr-4 font-medium">Engine</th>
                <th className="pb-2 pr-4 font-medium">Mention rate</th>
                <th className="pb-2 pr-4 font-medium">95% range</th>
                <th className="pb-2 pr-4 font-medium">Answers</th>
                <th className="pb-2 font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {m.engines.map((e) => (
                <tr key={e.surface} className="border-t border-[var(--border)]">
                  <td className="py-1.5 pr-4">{surfaceLabel(e.surface)}</td>
                  <td className="py-1.5 pr-4 font-medium tabular-nums">{e.rate}%</td>
                  <td className="py-1.5 pr-4 tabular-nums text-[var(--text-2)]">
                    {e.low}–{e.high}%
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums text-[var(--text-3)]">{e.answers}</td>
                  <td className="py-1.5 text-xs">
                    <ChangeBadge change={e.change} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

export default async function ScorecardPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, sc, acc] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<KpiScorecard>(`/api/tenant/kpi-scorecard${rangeQuery(from, to)}`),
    apiFetch<AccuracyReport>(`/api/tenant/accuracy${rangeQuery(from, to)}`),
  ]);
  if (sc.status === 403) {
    return <NoOrgNotice active="Scorecard" isSuperadmin={me.data?.is_superadmin} detail={sc.error} />;
  }
  const d = sc.data;
  if (!d || d.prominence.measured === 0) {
    return (
      <main className="mx-auto max-w-[1400px] px-6 pb-16">
        <DashNav active="Scorecard" isSuperadmin={me.data?.is_superadmin} withDateRange />
        <section className="card p-4">
          <h2 className="mb-2 text-lg font-medium">No scorecard yet</h2>
          <p className="text-sm text-[var(--text-2)]">
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
    color: colors.get(s.name) ?? "#9a9a92",
  }));
  const pd = d.prominence.position_distribution;
  const maxRate = Math.max(...d.stability.series.map((s) => s.presence_rate), 1);

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Scorecard" isSuperadmin={me.data?.is_superadmin} withDateRange />

      {d.mention_rates && d.mention_rates.overall.answers > 0 && (
        <MentionRatePanel m={d.mention_rates} brand={d.brand_name} />
      )}

      {/* Prominence-weighted share: useful, but rank is noisy run to run. */}
      <section className="card mb-6 p-4">
        <div className="flex flex-wrap items-start justify-between gap-10">
          <div>
            <p className="eyebrow mb-2">Answer share · {d.brand_name} · directional</p>
            <div className="flex items-baseline gap-2">
              <span className="text-6xl font-semibold leading-none tabular-nums text-[var(--text)]">
                {d.answer_share}%
              </span>
            </div>
            <p className="mt-3 max-w-md text-xs leading-relaxed text-[var(--text-3)]">
              Your share of AI answers compared with competitors, weighted by prominence. Being
              named earlier and more often counts for more. Treat it as directional: where a
              brand is listed varies a lot from one answer to the next.
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
          label="Lead rate (named first)"
          sub="of queries where you appear"
        />
        <Tile
          value={d.prominence.avg_rank === null ? "—" : `#${d.prominence.avg_rank}`}
          label="Average position when named"
          sub="directional: order varies run to run"
        />
        <div className="card p-4">
          <div className={`text-3xl font-semibold ${STABILITY_STYLE[d.stability.label] ?? ""}`}>
            {d.stability.label}
          </div>
          <div className="mt-1 text-sm text-[var(--text-2)]">Stability</div>
          <div className="text-xs text-[var(--text-3)]">
            {d.stability.swing}pt swing over {d.stability.series.length} runs
          </div>
        </div>
      </div>

      {acc.data && acc.data.facts_on_file > 0 && (
        <section className="card mb-6 p-4">
          <div className="mb-1 flex items-center justify-between gap-3">
            <h2 className="text-sm font-medium text-[var(--text-2)]">
              Factual accuracy
            </h2>
            <span
              className="chip"
              style={
                acc.data.error_count === 0
                  ? undefined
                  : { background: "var(--line)", color: "var(--plane)" }
              }
            >
              {acc.data.error_count === 0
                ? "clean"
                : `${acc.data.error_count} error${acc.data.error_count > 1 ? "s" : ""}`}
            </span>
          </div>
          <p className="mb-3 text-xs text-[var(--text-3)]">
            Checked against {acc.data.facts_on_file} fact
            {acc.data.facts_on_file > 1 ? "s" : ""} on file. Incorrect statements about pricing
            or accreditation are usually traced to a page the engines cite; correcting that page
            is the fix.
          </p>
          {acc.data.error_count === 0 ? (
            <p className="text-sm text-[var(--pos)]">
              No contradictions found in the latest answers.
            </p>
          ) : (
            <ul className="space-y-2">
              {acc.data.errors.map((e, i) => (
                <li key={i} className="card-inset p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="chip text-[var(--neg)]">{e.category}</span>
                    <span className="font-medium text-[var(--text)]">{e.subject}</span>
                    <span className="text-xs text-[var(--text-3)]">
                      on {e.engines.join(", ")}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-[var(--text-2)]">{e.detail}</p>
                  {e.snippet && (
                    <p className="mt-1 text-xs italic text-[var(--text-3)]">“{e.snippet}”</p>
                  )}
                  {/* Close the loop: generate the corrective content EverPresent
                      would publish for this gap (§step 5). */}
                  <GenerateDraft factId={e.fact_id} />
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Prominence distribution */}
        <section className="card p-4">
          <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
            Position when named
          </h2>
          <HBars
            items={[
              { label: "Leads the answer (1st)", value: pd.leads, color: "#ff5a1f" },
              { label: "Second", value: pd.second, color: "#0d0d0d" },
              { label: "Third or later", value: pd.third_plus, color: "#9a9a92" },
            ]}
            max={Math.max(pd.leads, pd.second, pd.third_plus, 1)}
          />
          <p className="mt-3 text-xs text-[var(--text-3)]">
            Being <em>named</em> isn't the same as being <em>recommended</em>. Leading the
            answer is what moves buyers.
          </p>
        </section>

        {/* Sentiment / framing */}
        <section className="card p-4">
          <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
            How you&apos;re described
          </h2>
          <div className="mb-4 flex gap-4 text-sm">
            <span className="text-[var(--pos)]">▲ {d.sentiment.counts.positive} positive</span>
            <span className="text-[var(--text-2)]">● {d.sentiment.counts.neutral} neutral</span>
            <span className="text-[var(--neg)]">▼ {d.sentiment.counts.negative} negative</span>
          </div>
          {[...d.sentiment.examples.negative, ...d.sentiment.examples.positive]
            .slice(0, 3)
            .map((ex, i) => (
              <blockquote key={i} className="mb-2 border-l-2 border-[var(--border)] pl-3 text-xs text-[var(--text-2)]">
                "{ex.snippet}"
                <span className="mt-0.5 block text-[var(--text-3)]">
                  {ex.query} · {surfaceLabel(ex.surface)}
                </span>
              </blockquote>
            ))}
          {d.sentiment.counts.positive + d.sentiment.counts.negative === 0 && (
            <p className="text-xs text-[var(--text-3)]">Mostly neutral framing so far.</p>
          )}
        </section>
      </div>

      {/* Head-to-head */}
      <section className="mt-6 card p-4">
        <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
          Head-to-head
        </h2>
        <p className="mb-4 text-xs text-[var(--text-3)]">
          On queries where you and a rival are both named, how often you're named first.
        </p>
        {d.head_to_head.length === 0 ? (
          <p className="text-sm text-[var(--text-3)]">No shared appearances yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-[var(--text-2)]">
              <tr>
                <th className="py-2 pr-4">Competitor</th>
                <th className="pr-4">Shared queries</th>
                <th className="pr-4">You lead</th>
                <th>Win rate</th>
              </tr>
            </thead>
            <tbody>
              {d.head_to_head.map((h) => (
                <tr key={h.competitor} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-4">{h.competitor}</td>
                  <td className="pr-4 tabular-nums">{h.shared}</td>
                  <td className="pr-4 tabular-nums">{h.wins}</td>
                  <td
                    className={`tabular-nums ${h.win_rate >= 50 ? "text-[var(--pos)]" : "text-[var(--warn-t)]"}`}
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
        <section className="mt-6 card p-4">
          <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
            Presence rate over recent runs (durability)
          </h2>
          <div className="flex gap-2" style={{ height: 120 }}>
            {d.stability.series.map((s) => (
              <div key={s.run_id} className="flex h-full flex-1 flex-col items-center gap-1">
                {/* The bar's % height needs a definite-height parent. */}
                <div className="flex w-full flex-1 items-end">
                  <div
                    className="w-full bg-[var(--accent)]"
                    style={{ height: `${(s.presence_rate / maxRate) * 100}%`, minHeight: 2 }}
                    title={`Run #${s.run_id}: ${s.presence_rate}%`}
                  />
                </div>
                <span className="text-[10px] text-[var(--text-3)]">#{s.run_id}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
