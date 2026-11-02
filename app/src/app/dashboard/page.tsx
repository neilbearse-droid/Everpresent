import Link from "next/link";
import {
  apiFetch,
  rangeQuery,
  type Briefing,
  type EngineModesPayload,
  type Me,
  type OverviewPayload,
  type Run,
  type TenantSummary,
} from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { EngineStrip, ModeStack } from "@/components/engine-modes";
import { NoOrgNotice } from "@/components/no-org-notice";
import { TrendChart, HBars } from "@/components/charts";
import { entityColors, fmtDate, OTHER_COLOR } from "@/lib/viz";
import { Sparkline } from "@/components/sparkline";
import { BriefingBlock } from "./briefing";

const VERDICT_LABEL: Record<Briefing["winning"]["verdict"], string> = {
  gaining: "Gaining",
  losing: "Losing ground",
  holding: "Holding steady",
  baseline: "Building baseline",
  unknown: "Not measured yet",
};

const REPORTS: [string, string][] = [
  ["Client report (PDF)", "/dashboard/reports/summary.pdf"],
  ["Data workbook (Excel)", "/dashboard/reports/report.xlsx"],
  ["Results CSV", "/dashboard/reports/results.csv"],
  ["Visibility CSV", "/dashboard/reports/visibility.csv"],
];

/**
 * The Overview answers one question first: how often do AI answers name you?
 * One figure, the verdict, the reasons, and this week's list. Everything
 * else on the page is the detail behind that figure, in the order a client
 * would ask for it, and the downloads come last.
 */
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
  const brand = data?.brand_name ?? tenant.data.brand_name ?? tenant.data.name;
  const competitorNames = data
    ? [...new Set(data.trend.flatMap((t) => Object.keys(t.competitors)))]
    : [];
  // Rank rivals by share of voice so the chart shows the ones that matter.
  const shareOf = (name: string) => data?.share_of_voice[name] ?? 0;
  const rivalsByShare = [...competitorNames].sort(
    (a, b) => shareOf(b) - shareOf(a) || a.localeCompare(b),
  );
  const colors = entityColors(brand, rivalsByShare);

  const trendRows =
    data?.trend.map((point) => ({
      date: point.date,
      [brand]: point.brand_score,
      ...point.competitors,
    })) ?? [];
  const trendSeries = [brand, ...rivalsByShare]
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
      ? `${from} to ${to}`
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
  const measured = !!mr && mr.answers > 0;
  const b = briefing.data;
  const verdict: Briefing["winning"]["verdict"] = b
    ? b.winning.verdict
    : !measured
      ? "unknown"
      : mr.change.verdict === "up"
        ? "gaining"
        : mr.change.verdict === "down"
          ? "losing"
          : mr.change.verdict === "no real change"
            ? "holding"
            : "baseline";
  const topRival = b?.winning.top_rival
    ? b.winning.top_rival
    : rivalsByShare[0]
      ? { name: rivalsByShare[0], share: shareOf(rivalsByShare[0]) }
      : null;
  const lastMeasured = fmtDate(composite?.date ?? data?.latest?.date);
  const alerts = data?.alerts ?? [];

  // Before the first run there is nothing to score, so the page says what
  // happens next instead of showing dashes. The runs list is only fetched in
  // that state.
  const runs = !hasData ? (await apiFetch<Run[]>("/api/tenant/runs")).data ?? [] : [];

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav
        active="Overview"
        isSuperadmin={me.data?.is_superadmin}
        withDateRange
      />

      {!hasData ? (
        <FirstWeek tenant={tenant.data} runs={runs} />
      ) : (
        <>
          {/* 1. The one number. */}
          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-12">
            <div className="p-6 lg:col-span-7">
              <div className="flex flex-wrap items-center gap-2">
                <span className="bp-label">{brand} · Named in AI answers</span>
                <span
                  className={`pill ${
                    verdict === "gaining"
                      ? "pill-good"
                      : verdict === "losing"
                        ? "pill-bad"
                        : ""
                  }`}
                >
                  {VERDICT_LABEL[verdict]}
                  {measured &&
                  mr.change.delta !== null &&
                  (mr.change.verdict === "up" || mr.change.verdict === "down")
                    ? ` · ${mr.change.verdict === "up" ? "+" : "−"}${Math.abs(mr.change.delta)} pts`
                    : ""}
                </span>
              </div>
              <div className="ep-hero-figure mt-4">
                {measured ? (
                  <>
                    {mr.rate}
                    <small>%</small>
                  </>
                ) : (
                  "—"
                )}
              </div>
              <p className="mt-3 max-w-xl text-[14px] leading-relaxed text-[var(--text)]">
                {b?.winning.line ||
                  (measured
                    ? `${brand} is named in ${mr.rate}% of the AI answers measured about your category.`
                    : "The headline rate appears once the first run has been processed.")}
              </p>
              {b?.focus && (
                <p className="mt-3 text-[13px] text-[var(--text-2)]">
                  <span className="font-semibold text-[var(--text)]">Focus: </span>
                  {b.focus}
                </p>
              )}
            </div>
            <div className="bp-stack lg:col-span-5">
              <div className="p-5">
                <div className="flex items-baseline justify-between">
                  <span className="bp-label">Trend</span>
                  <span className="text-xs text-[var(--text-3)]">
                    {fmtDate(trendRows[0].date)} – {fmtDate(trendRows[trendRows.length - 1].date)}
                  </span>
                </div>
                <div className="mt-3">
                  <Sparkline
                    values={(data?.trend ?? []).map((t) => t.brand_score)}
                    label={`${brand} visibility over time`}
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-px bg-[var(--line)] [&>*]:bg-[var(--surface)]">
                <div className="px-5 py-4">
                  <div className="bp-label">Share of voice</div>
                  <div className="bp-metric mt-1.5 text-[22px]">
                    {data && data.share_of_voice[brand] !== undefined
                      ? `${data.share_of_voice[brand]}%`
                      : "—"}
                  </div>
                </div>
                <div className="px-5 py-4">
                  <div className="bp-label">Top rival</div>
                  <div className="mt-1.5 truncate text-[15px] font-semibold tracking-[-0.02em]">
                    {topRival?.name ?? "—"}
                  </div>
                  {topRival && (
                    <div className="text-[11px] tabular-nums text-[var(--text-3)]">
                      {topRival.share}% share
                    </div>
                  )}
                </div>
                <div className="px-5 py-4">
                  <div className="bp-label">Last measured</div>
                  <div className="mt-1.5 text-[15px] font-semibold tracking-[-0.02em]">
                    {lastMeasured || "—"}
                  </div>
                </div>
              </div>
            </div>
            {/* The method sits under the number, open on request. */}
            <details className="lg:col-span-12">
              <summary className="cursor-pointer px-6 py-3 text-[12.5px] font-medium text-[var(--text-3)] hover:text-[var(--text-2)]">
                How this number is measured
              </summary>
              <div className="grid gap-x-8 gap-y-2 border-t border-[var(--line)] px-6 py-4 text-[12.5px] leading-relaxed text-[var(--text-2)] md:grid-cols-2">
                <p>
                  <span className="font-semibold text-[var(--text)]">The rate. </span>
                  The share of AI answers to your tracked questions that name {brand}.
                  {measured && (
                    <>
                      {" "}
                      Across {mr.answers.toLocaleString()} answers the 95% range is {mr.low}–
                      {mr.high}%; movement inside that range is noise, not news.
                    </>
                  )}
                  {mr?.weighting === "audience" &&
                    " Engines are weighted by audience share, so the engines more people use count for more."}
                </p>
                <p>
                  <span className="font-semibold text-[var(--text)]">The verdict. </span>
                  Compares this period with the previous one and only calls a change when the
                  ranges don&apos;t overlap. The{" "}
                  <Link href="/dashboard/scorecard" className="bp-link">
                    Scorecard
                  </Link>{" "}
                  shows the rate per engine, the rate without forced web search, and the smallest
                  change the current schedule can detect.
                </p>
                {(data?.series_notes ?? []).map((n) => (
                  <p key={`${n.surface}-${n.date}`} className="md:col-span-2">
                    <span className="font-semibold text-[var(--text)]">
                      Measurement change, {n.date}.{" "}
                    </span>
                    {n.note}
                  </p>
                ))}
              </div>
            </details>
          </section>

          {/* 2. Why, and what to do this week. */}
          {b ? (
            <BriefingBlock b={b} alerts={alerts} />
          ) : (
            alerts.length > 0 && <AlertsList alerts={alerts} />
          )}

          {/* 3. The numbers behind it. */}
          <div className="mb-3 mt-10 flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold tracking-[-0.01em]">The numbers behind it</h2>
            <span className="text-xs text-[var(--text-3)]">
              Per engine, by how the engine answered, and against each rival
            </span>
          </div>

          {modes?.observed && (
            <section className="mb-6">
              <EngineStrip data={modes} />
            </section>
          )}

          {/* Asymmetric row: trend (8) + mode stack (4). */}
          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-12">
            <div className="lg:col-span-8">
              <div className="bp-bar">
                <span>Visibility score trend</span>
                <span>
                  {composite ? `Today ${composite.score} · ` : ""}0–100, against each rival
                </span>
              </div>
              <div className="p-4">
                {trendRows.length >= 2 ? (
                  <TrendChart data={trendRows} series={trendSeries} />
                ) : (
                  <p className="py-16 text-center text-sm text-[var(--text-3)]">
                    The trend line appears after a second day of measurements.
                  </p>
                )}
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
          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-12">
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
                      <th>Brand</th>
                      <th className="text-right">Change</th>
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
                          <td className="text-right font-mono">{mover.before}</td>
                          <td className="text-right font-mono">{mover.after}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          {/* 4. Take it with you. */}
          <section className="flex flex-wrap items-center gap-2 border-t border-[var(--line)] pt-5">
            <span className="mr-2 text-[13px] font-medium text-[var(--text-2)]">Reports</span>
            {REPORTS.map(([label, href]) => (
              <a key={href} href={href} className="btn btn-ghost px-3 text-[12.5px]">
                {label} <span aria-hidden>↓</span>
              </a>
            ))}
          </section>
        </>
      )}
    </main>
  );
}

/** "What changed" on its own, for the rare case the briefing endpoint is down. */
function AlertsList({ alerts }: { alerts: NonNullable<OverviewPayload["alerts"]> }) {
  return (
    <section className="blueprint mb-6 grid-cols-1">
      <div>
        <div className="bp-bar">
          <span>What changed</span>
          <span>{alerts.length}</span>
        </div>
        <ul>
          {alerts.map((a, i) => (
            <li
              key={i}
              className="flex items-start gap-3 border-t border-[var(--line)] px-4 py-2.5 text-[13px] first:border-t-0"
            >
              <span
                className={`bp-label shrink-0 px-1.5 ${
                  a.severity === "high" ? "bp-neg" : a.severity === "good" ? "bp-mark" : ""
                }`}
              >
                {a.severity === "high" ? "Act" : a.severity === "good" ? "Win" : "Watch"}
              </span>
              <span className="text-[var(--text)]">{a.text}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/**
 * Before the first completed run: the four steps of the first week, with the
 * ones already done ticked, instead of a page of dashes.
 */
function FirstWeek({ tenant, runs }: { tenant: TenantSummary; runs: Run[] }) {
  const latest = runs[0] ?? null;
  const live = latest && (latest.status === "pending" || latest.status === "running");
  const failed = latest && (latest.status === "failed" || latest.status === "capped" || latest.status === "gated");
  const setUp = tenant.counts.queries > 0;
  const steps: { title: string; body: string; state: "done" | "now" | "next" }[] = [
    {
      title: "Your questions are chosen",
      body: setUp
        ? `${tenant.counts.queries} questions, ${tenant.counts.competitors} competitors tracked. Review or pause any of them on the Queries page.`
        : "Your EverPresent contact drafts the questions your buyers ask and you approve the list.",
      state: setUp ? "done" : "now",
    },
    {
      title: "The engines get asked",
      body: live
        ? "The first run is in progress. Browser engines take the longest; this usually finishes within the hour."
        : failed
          ? "The first run hit a problem and is being looked at. Nothing is lost; it resumes where it stopped."
          : latest
            ? "The first run has finished and its answers are being processed."
            : "Every engine you turned on gets your questions, from a clean session in your market.",
      state: setUp ? (latest ? "done" : "now") : "next",
    },
    {
      title: "Your first number",
      body: "How often AI answers name you, which rival they name instead, and what they get wrong. This page fills in the day the first run is processed.",
      state: setUp && latest && !live && !failed ? "now" : "next",
    },
    {
      title: "A trend you can act on",
      body: "After the second run the trend line starts, and after a week the changes are big enough to tell from noise.",
      state: "next",
    },
  ];
  return (
    <section className="blueprint grid-cols-1 lg:grid-cols-12">
      <div className="p-6 lg:col-span-5">
        <span className="bp-label">{tenant.brand_name ?? tenant.name} · Named in AI answers</span>
        <div className="ep-hero-figure mt-4 text-[var(--text-3)]">—</div>
        <p className="mt-3 max-w-md text-[14px] leading-relaxed text-[var(--text)]">
          Your first week. This page becomes one number, the reasons behind it, and a short list of
          what to do, as soon as the first run is processed.
        </p>
        <p className="mt-4 text-[13px] text-[var(--text-2)]">
          <Link href="/dashboard/queries" className="bp-link">
            See your questions
          </Link>
          <span className="px-2 text-[var(--border-strong)]">·</span>
          <Link href="/dashboard/runs" className="bp-link">
            See runs
          </Link>
        </p>
      </div>
      <ol className="lg:col-span-7">
        {steps.map((s, i) => (
          <li
            key={s.title}
            className={`flex gap-4 border-t border-[var(--line)] px-6 py-4 first:border-t-0 lg:first:border-t-0 ${
              s.state === "next" ? "opacity-60" : ""
            }`}
          >
            <span
              className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11.5px] font-semibold tabular-nums ${
                s.state === "done"
                  ? "bg-[var(--accent)] text-white"
                  : s.state === "now"
                    ? "border-2 border-[var(--accent)] text-[var(--text)]"
                    : "bg-[var(--plane-2)] text-[var(--text-2)]"
              }`}
              aria-label={s.state === "done" ? "done" : s.state === "now" ? "in progress" : "next"}
            >
              {s.state === "done" ? "✓" : i + 1}
            </span>
            <span className="min-w-0">
              <span className="block text-[14px] font-semibold">
                {s.title}
                {s.state === "now" && (
                  <span className="ml-2 text-[11.5px] font-medium text-[var(--accent-display)]">
                    now
                  </span>
                )}
              </span>
              <span className="mt-0.5 block text-[13px] leading-relaxed text-[var(--text-2)]">
                {s.body}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
