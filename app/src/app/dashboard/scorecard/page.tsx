import {
  apiFetch,
  rangeQuery,
  type AccuracyReport,
  type KpiScorecard,
  type SamplePlan,
  type Me,
  type MentionRates,
  type TopicRow,
  type RateChange,
} from "@/lib/api";
import { GenerateDraft } from "./generate-draft";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { HBars } from "@/components/charts";
import { entityColors, OTHER_COLOR, surfaceLabel } from "@/lib/viz";
import { Delta, EngineMark, Linkify, Mark } from "@/components/ui";
import { AddToPlan } from "@/components/plan-buttons";

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
    return (
      <span className="text-[13px]">
        <Delta value={change.delta} unit=" pts" />
      </span>
    );
  }
  return (
    <span className="text-xs text-[var(--text-3)]">
      {change.verdict === "no real change" ? "no real change" : "not enough data"}
    </span>
  );
}

/** How big a change the current setup can see, per engine: turns "not enough
 * data yet" into a number and a next step. */
function SamplePlanPanel({ p }: { p: SamplePlan }) {
  return (
    <section className="blueprint mt-6 grid-cols-1">
      <div className="bp-bar">
        <span>Detectable change</span>
        <span>
          {p.window_days}-day window · {p.runs_per_week ? `${p.runs_per_week} runs/week` : "no schedule"}
        </span>
      </div>
      <div>
        <div className="overflow-x-auto">
          <table className="bp-table mt-2 w-full min-w-[640px]">
            <thead>
              <tr>
                <th>Engine</th>
                <th className="text-right">Answers / 2 wks</th>
                <th className="text-right">Needed ({p.target_change_pts} pts)</th>
                <th className="text-right">Detectable</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {p.engines.map((e) => (
                <tr key={e.surface}>
                  <td className="font-semibold">
                    <span className="inline-flex items-center gap-2">
                      <EngineMark surface={e.surface} size={16} />
                      {e.label}
                    </span>
                  </td>
                  <td className="text-right tabular-nums">{e.answers_per_half_window}</td>
                  <td className="text-right tabular-nums">{e.needed_per_half_window}</td>
                  <td className="text-right tabular-nums">
                    {e.detectable_change_pts ? `±${e.detectable_change_pts} pts` : "—"}
                  </td>
                  <td className="text-[12.5px]">
                    {e.can_detect_target ? (
                      <span className="bp-mark">ready{e.ready_by ? ` from ${e.ready_by}` : ""}</span>
                    ) : e.too_few_to_plan ? (
                      <span className="text-[var(--text-3)]">too few answers to plan yet</span>
                    ) : e.more_answers_needed_x ? (
                      <span className="text-[var(--text-2)]">needs {e.more_answers_needed_x}× more answers</span>
                    ) : (
                      <span className="text-[var(--text-3)]">needs a schedule</span>
                    )}
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

/** The headline: how often AI answers name you, with an honest range. Answers
 * vary run to run, so a single reading is noise; the pooled rate isn't. */
function MentionRatePanel({ m, brand }: { m: MentionRates; brand: string }) {
  const o = m.overall;
  return (
    <section className="card mb-6 p-4">
      <div className="flex flex-wrap items-start justify-between gap-10">
        <div>
          <h2 className="mb-2 text-sm font-medium text-[var(--text-2)]">{brand} mention rate</h2>
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
              {o.answers} answers · {o.prompts} questions · {m.window.start} to {m.window.end}
            </span>
          </div>
          {o.unforced && o.unforced.answers > 0 && (
            <div className="mt-4 border-t border-[var(--border)] pt-3">
              <p className="text-xs font-medium text-[var(--text-2)]">Without forced search</p>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-semibold tabular-nums">{o.unforced.rate}%</span>
                <span className="text-sm tabular-nums text-[var(--text-2)]">
                  ({o.unforced.low}–{o.unforced.high}%)
                </span>
              </div>
            </div>
          )}
        </div>
        <div className="min-w-72 flex-1 overflow-x-auto">
          <p className="bp-label mb-2">By engine</p>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs text-[var(--text-3)]">
                <th className="pb-2 pr-4 font-medium">Engine</th>
                <th className="pb-2 pr-4 font-medium">Rate</th>
                <th className="pb-2 pr-4 font-medium">Range</th>
                <th className="pb-2 pr-4 font-medium">Unforced</th>
                <th className="pb-2 pr-4 font-medium">Searched</th>
                <th className="pb-2 pr-4 font-medium">Answers</th>
                <th className="pb-2 font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {m.engines.map((e) => (
                <tr key={e.surface} className="border-t border-[var(--border)]">
                  <td className="py-1.5 pr-4">
                    <span className="inline-flex items-center gap-2">
                      <EngineMark surface={e.surface} size={16} />
                      {surfaceLabel(e.surface)}
                    </span>
                    {e.forced && (
                      <span className="ml-1.5 text-[11px] text-[var(--text-3)]">forced</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-4 font-semibold tabular-nums">{e.rate}%</td>
                  <td className="py-1.5 pr-4 tabular-nums text-[var(--text-2)]">
                    {e.low}–{e.high}%
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums">
                    {!e.forced ? (
                      <span className="text-[var(--text-3)]">same</span>
                    ) : e.unforced && e.unforced.answers > 0 ? (
                      <>
                        <span className="font-medium">{e.unforced.rate}%</span>{" "}
                        <span className="text-xs text-[var(--text-3)]">
                          {e.unforced.low}–{e.unforced.high}%
                        </span>
                      </>
                    ) : (
                      <span className="text-xs text-[var(--text-3)]">—</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums text-[var(--text-2)]">
                    {e.unforced?.searched_rate != null ? `${e.unforced.searched_rate}%` : "—"}
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

/** The headline numbers per question topic, so a strong topic can't hide a
 * weak one. Branded questions name the brand by design, so they get their own
 * measures instead of a mention rate. */
function TopicPanel({ rows, brand, overall }: { rows: TopicRow[]; brand: string; overall: number | null }) {
  const topics = rows.filter((r) => r.kind !== "branded").sort((a, b) => a.rate - b.rate);
  const branded = rows.find((r) => r.kind === "branded");
  const sentimentTotal = branded
    ? branded.sentiment.positive + branded.sentiment.neutral + branded.sentiment.negative
    : 0;
  const pct = (n: number) => (sentimentTotal ? Math.round((100 * n) / sentimentTotal) : 0);
  return (
    <section className="card mb-6 p-4">
      <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">By topic</h2>
      {topics.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs text-[var(--text-3)]">
                <th className="pb-2 pr-4 font-medium">Topic</th>
                <th className="pb-2 pr-4 font-medium">Questions</th>
                <th className="pb-2 pr-4 font-medium">Rate</th>
                <th className="pb-2 pr-4 font-medium">Range</th>
                <th className="pb-2 pr-4 font-medium">Answer share</th>
                <th className="pb-2 pr-4 font-medium">Named first</th>
                <th className="pb-2 pr-4 font-medium">Top rival</th>
                <th className="pb-2 pr-4 font-medium">Change</th>
                <th className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {topics.map((r) => (
                <tr key={r.topic} className="border-t border-[var(--border)]">
                  <td className="py-1.5 pr-4 font-semibold">
                    {r.topic}
                    {r.kind === "agent" && (
                      <span className="ml-2 text-xs font-normal text-[var(--text-3)]">agent</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums text-[var(--text-3)]">{r.questions}</td>
                  <td className={`py-1.5 pr-4 tabular-nums ${overall !== null && r.rate < overall ? "font-semibold" : ""}`}>
                    {overall !== null && r.rate < overall ? <span className="bp-neg">{r.rate}%</span> : <>{r.rate}%</>}
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums text-[var(--text-2)]">
                    {r.low}–{r.high}%
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums">{r.answer_share}%</td>
                  <td className="py-1.5 pr-4 tabular-nums">{r.lead_rate}%</td>
                  <td className="py-1.5 pr-4 text-[var(--text-2)]">
                    {r.top_rival ? (
                      <>
                        <span className="font-medium text-[var(--text)]">{r.top_rival.name}</span>{" "}
                        <span className="text-xs tabular-nums">{r.top_rival.share}%</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="py-1.5 pr-4 text-xs">
                    <ChangeBadge change={r.change} />
                  </td>
                  <td className="py-1.5">
                    {overall !== null && r.rate < overall && (
                      <AddToPlan
                        gapRef={`topic:${r.topic}`}
                        title={`Write for ${r.topic}`}
                        actionText={`${brand} is named in ${r.rate}% of ${r.topic} answers against ${overall}% overall${r.top_rival ? `; ${r.top_rival.name} leads at ${r.top_rival.share}%` : ""}.`}
                        link="/dashboard/scorecard"
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {branded && branded.answers > 0 && (
        <div className="mt-5 border-t border-[var(--border)] pt-4">
          <p className="mb-3 text-sm font-medium">
            {branded.topic}
            <span className="ml-2 text-xs font-normal text-[var(--text-3)]">
              {branded.questions} {branded.questions === 1 ? "question" : "questions"} that name {brand}
            </span>
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile
              value={`${pct(branded.sentiment.positive)}%`}
              label="Positive"
              sub={`${pct(branded.sentiment.negative)}% negative, the rest neutral`}
            />
            <Tile
              value={`${branded.rivals_named_rate}%`}
              label="Answers that also name a rival"
              sub={branded.top_rival ? `Most often ${branded.top_rival.name}` : undefined}
            />
            <Tile value={`${branded.cited_rate}%`} label={`Answers citing ${brand}'s site`} />
            <Tile value={`${branded.lead_rate}%`} label={`${brand} named first`} />
          </div>
        </div>
      )}
    </section>
  );
}

export default async function ScorecardPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, sc, acc, plan] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<KpiScorecard>(`/api/tenant/kpi-scorecard${rangeQuery(from, to)}`),
    apiFetch<AccuracyReport>(`/api/tenant/accuracy${rangeQuery(from, to)}`),
    apiFetch<SamplePlan>("/api/tenant/sample-plan"),
  ]);
  if (sc.status === 403) {
    return <NoOrgNotice active="Scorecard" isSuperadmin={me.data?.is_superadmin} detail={sc.error} />;
  }
  const d = sc.data;
  if (!d || d.prominence.measured === 0) {
    return (
      <main className="mx-auto max-w-[1400px] px-6 pb-16">
        <DashNav active="Scorecard" isSuperadmin={me.data?.is_superadmin} withDateRange />
        <PageLead
          tells="No scorecard yet; it fills in after the first run."
          act="Send your EverPresent contact the facts you want checked."
        />
      </main>
    );
  }

  const colors = entityColors(
    d.brand_name,
    [...d.share_breakdown].sort((a, b) => b.share - a.share).map((s) => s.name),
  );
  const shareItems = d.share_breakdown.map((s) => ({
    label: s.name,
    value: s.share,
    color: colors.get(s.name) ?? OTHER_COLOR,
  }));
  const pd = d.prominence.position_distribution;
  const maxRate = Math.max(...d.stability.series.map((s) => s.presence_rate), 1);

  // The lead: the pooled rate and its verdict, the weakest topic, and the
  // wrong facts, in that order of urgency. Wrong facts come first because
  // each traces to a page you can correct this week.
  const o = d.mention_rates && d.mention_rates.overall.answers > 0 ? d.mention_rates.overall : null;
  const topics = (d.by_topic ?? []).filter((r) => r.kind !== "branded" && r.answers > 0);
  const weakest = topics.length > 1 ? [...topics].sort((a, b) => a.rate - b.rate)[0] : null;
  const errors = acc.data?.error_count ?? 0;
  const verdict = o?.change.verdict ?? "not enough data";
  const trailing = d.head_to_head.filter((h) => h.shared >= 3 && h.win_rate < 50);
  const delta = Math.abs(o?.change.delta ?? 0);
  const lead = {
    tells: o ? (
      <>
        Named in {o.rate}% of AI answers
        {verdict === "up" ? <>, up {delta} points.</> : verdict === "down" ? <>, down {delta} points.</> : <>.</>}
      </>
    ) : (
      <>Named in {d.prominence.presence_rate}% of the latest answers.</>
    ),
    act:
      errors > 0
        ? `Fix the ${errors} wrong ${errors === 1 ? "fact" : "facts"} first; drafts are below.`
        : weakest && o && weakest.rate < o.rate
          ? `Write for ${weakest.topic}, your weakest topic at ${weakest.rate}%.`
          : trailing.length > 0
            ? `Beat ${trailing[0].competitor} on the questions you share.`
            : "Hold what's winning.",
    href: errors > 0 ? undefined : weakest && o && weakest.rate < o.rate ? "/dashboard/action-plan" : trailing.length > 0 ? "/dashboard/queries" : undefined,
    hrefLabel: weakest && o && weakest.rate < o.rate ? "Action Plan" : "Queries",
    tone: (errors > 0 || verdict === "down" ? "bad" : verdict === "up" ? "good" : "neutral") as "good" | "bad" | "neutral",
  };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Scorecard" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      {d.mention_rates && d.mention_rates.overall.answers > 0 && (
        <MentionRatePanel m={d.mention_rates} brand={d.brand_name} />
      )}
      {d.by_topic && d.by_topic.length > 0 && (
        <TopicPanel rows={d.by_topic} brand={d.brand_name} overall={o ? o.rate : null} />
      )}

      {/* Prominence-weighted share: useful, but rank is noisy run to run. */}
      <section className="card mb-6 p-4">
        <div className="flex flex-wrap items-start justify-between gap-10">
          <div>
            <h2 className="mb-2 text-sm font-medium text-[var(--text-2)]">{d.brand_name} answer share</h2>
            <div className="flex items-baseline gap-2">
              <span className="text-6xl font-semibold leading-none tabular-nums text-[var(--text)]">
                {d.answer_share}%
              </span>
            </div>
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
          sub="rough guide: order varies run to run"
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
                  : { background: "var(--ink)", color: "var(--ink-text)" }
              }
            >
              {acc.data.error_count === 0
                ? "clean"
                : `${acc.data.error_count} error${acc.data.error_count > 1 ? "s" : ""}`}
            </span>
          </div>
          {acc.data.error_count === 0 ? (
            <p className="text-sm text-[var(--text-2)]">▲ No wrong facts in the latest answers.</p>
          ) : (
            <ul className="space-y-2">
              {acc.data.errors.map((e, i) => (
                <li key={i} className="card-inset flex gap-2 p-3 text-sm">
                  <Mark tone="bad" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-[var(--text)]">{e.subject}</span>
                      <span className="chip">{e.category}</span>
                      <span className="inline-flex items-center gap-1">
                        {e.engines.map((en) => (
                          <EngineMark key={en} surface={en} size={16} />
                        ))}
                      </span>
                    </div>
                    <p className="mt-1 text-[13px] text-[var(--text-2)]">
                      <span className="bp-neg">Says</span> {e.stated}
                      <span className="mx-2 text-[var(--text-3)]">·</span>
                      <span className="font-semibold text-[var(--text)]">Fact</span> {e.expected}
                    </p>
                    {e.detail && e.detail !== e.stated && (
                      <p className="mt-1 text-xs text-[var(--text-3)]">
                        <Linkify text={e.detail} />
                      </p>
                    )}
                    {e.snippet && (
                      <p className="mt-1 text-xs italic text-[var(--text-3)]">“{e.snippet}”</p>
                    )}
                    <div className="mt-2 flex flex-wrap items-start gap-2">
                      <AddToPlan
                        gapRef={`fact:${e.fact_id}`}
                        title={`Correct the ${e.subject} fact`}
                        actionText={`Engines say "${e.stated}"; the fact is "${e.expected}". Fix the page that taught it and request a recrawl.`}
                        link="/dashboard/scorecard"
                      />
                      {/* Close the loop: generate the corrective content EverPresent
                          would publish for this gap (§step 5). */}
                      <GenerateDraft factId={e.fact_id} />
                    </div>
                  </div>
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
              { label: "Second", value: pd.second, color: "var(--text)" },
              { label: "Third or later", value: pd.third_plus, color: OTHER_COLOR },
            ]}
            max={Math.max(pd.leads, pd.second, pd.third_plus, 1)}
          />
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
              <blockquote key={i} className="mb-2 border-l border-[var(--border)] pl-3 text-xs text-[var(--text-2)]">
                "{ex.snippet}"
                <span className="mt-0.5 flex items-center gap-1.5 text-[var(--text-3)]">
                  <EngineMark surface={ex.surface} size={14} />
                  {surfaceLabel(ex.surface)} · {ex.query}
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
        <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">Head to head</h2>
        {d.head_to_head.length === 0 ? (
          <p className="text-sm text-[var(--text-3)]">No shared appearances yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-[var(--text-2)]">
              <tr>
                <th className="py-2 pr-4">Competitor</th>
                <th className="pr-4">Shared</th>
                <th className="pr-4">You first</th>
                <th className="pr-4">Win rate</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {d.head_to_head.map((h) => (
                <tr key={h.competitor} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-4 font-semibold">{h.competitor}</td>
                  <td className="pr-4 tabular-nums text-[var(--text-2)]">{h.shared}</td>
                  <td className="pr-4 tabular-nums text-[var(--text-2)]">{h.wins}</td>
                  <td className="pr-4 tabular-nums">
                    {h.win_rate >= 50 ? (
                      <span className="font-semibold">▲ {h.win_rate}%</span>
                    ) : (
                      <span className="bp-neg">▼ {h.win_rate}%</span>
                    )}
                  </td>
                  <td>
                    {h.shared >= 3 && h.win_rate < 50 && (
                      <AddToPlan
                        gapRef={`rival:${h.competitor}`}
                        title={`Beat ${h.competitor} on shared questions`}
                        actionText={`${h.competitor} is named ahead of ${d.brand_name} on ${h.shared - h.wins} of ${h.shared} shared questions.`}
                        link="/dashboard/queries"
                      />
                    )}
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
            Presence rate over recent runs
          </h2>
          <div className="flex gap-2" style={{ height: 120 }}>
            {d.stability.series.map((s) => (
              <div key={s.run_id} className="flex h-full flex-1 flex-col items-center gap-1">
                {/* The bar's % height needs a definite-height parent. */}
                <div className="flex w-full flex-1 flex-col items-center justify-end border-b border-[var(--line)]">
                  <span className="mb-1 text-[11px] font-medium tabular-nums">
                    {s.presence_rate}%
                  </span>
                  <div
                    className="w-full max-w-[56px] rounded-t-md bg-[var(--accent)]"
                    style={{ height: `${(s.presence_rate / maxRate) * 80}%`, minHeight: 2 }}
                    title={`Run #${s.run_id}: ${s.presence_rate}%`}
                  />
                </div>
                <span className="text-[10px] text-[var(--text-3)]">#{s.run_id}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* The method, last: how big a change this schedule can see. */}
      {plan.data && plan.data.engines.length > 0 && <SamplePlanPanel p={plan.data} />}
    </main>
  );
}
