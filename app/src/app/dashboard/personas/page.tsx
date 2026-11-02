import { apiFetch, rangeQuery, type Me, type PersonasPayload } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { HBars } from "@/components/charts";
import { SERIES_COLORS, humanize } from "@/lib/viz";

export default async function PersonasPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, personas] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<PersonasPayload>(`/api/tenant/personas-intel${rangeQuery(from, to)}`),
  ]);
  if (personas.status === 403) {
    return (
      <NoOrgNotice active="Personas" isSuperadmin={me.data?.is_superadmin} detail={personas.error} />
    );
  }
  const data = personas.data;

  // The lead: which buyer you're strongest and weakest with, and where a
  // rival is ahead of you.
  const segs = data?.segments ?? [];
  const byScore = [...segs].sort((a, b) => b.brand_score - a.brand_score);
  const best = byScore[0] ?? null;
  const worst = byScore[byScore.length - 1] ?? null;
  const behind = segs
    .map((s) => {
      const top = Object.entries(s.competitor_scores).sort((a, b) => b[1] - a[1])[0];
      return top && top[1] > s.brand_score
        ? { segment: s.segment, rival: top[0], gap: Math.round((top[1] - s.brand_score) * 100) / 100 }
        : null;
    })
    .filter((x): x is { segment: string; rival: string; gap: number } => x !== null)
    .sort((a, b) => b.gap - a.gap);
  const lead =
    segs.length === 0
      ? {
          tells: "No persona answers yet. A persona asks the same question as a particular buyer; this page shows whether the engines name you for each kind of buyer.",
          act: "Tick a persona against the questions that matter on the Queries page, and the next run asks them that way.",
          href: "/dashboard/queries",
          hrefLabel: "Choose personas",
          tone: "neutral" as const,
        }
      : {
          tells: (
            <>
              You&apos;re strongest with {humanize(best!.segment)} (score {best!.brand_score})
              {segs.length > 1 ? <> and weakest with {humanize(worst!.segment)} ({worst!.brand_score})</> : null}.
              {behind.length > 0 ? (
                <>
                  {" "}
                  {behind[0].rival} is ahead of you with {humanize(behind[0].segment)} by {behind[0].gap}
                  {behind.length > 1 ? <>, and rivals lead you with {behind.length - 1} other {behind.length - 1 === 1 ? "persona" : "personas"}</> : null}.
                </>
              ) : (
                <> No rival is ahead of you with any persona.</>
              )}
            </>
          ),
          act:
            behind.length > 0
              ? `If ${humanize(behind[0].segment)} is a buyer you want, read their answers on the questions you lose and write for what they ask about. The brief for each question is on the Action Plan.`
              : "Nothing to fix by persona. Keep the questions these buyers ask in the set, and watch for a rival pulling ahead after a model change.",
          href: behind.length > 0 ? "/dashboard/action-plan" : undefined,
          hrefLabel: "Action Plan",
          tone: (behind.length === 0 ? "good" : behind.length >= segs.length ? "bad" : "neutral") as "good" | "bad" | "neutral",
        };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Personas" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      {!data || data.segments.length === 0 ? (
        <section className="card p-4">
          <h2 className="mb-2 text-lg font-medium">No persona data yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Visibility by persona appears after the first completed run.
            {personas.error ? ` (${personas.error})` : ""}
          </p>
        </section>
      ) : (
        <>
          <section className="mb-6 card p-4">
            <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
              Brand visibility by persona · {data.date}
            </h2>
            {/* Single measure across personas: one hue, no legend. */}
            <HBars
              items={data.segments.map((s) => ({
                label: humanize(s.segment),
                value: s.brand_score,
                color: SERIES_COLORS[0],
              }))}
            />
          </section>

          <section className="card p-4">
            <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
              By persona
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-[var(--text-2)]">
                  <tr>
                    <th className="py-2 pr-4">Persona</th>
                    <th className="pr-4">Brand score</th>
                    <th className="pr-4">Mention rate</th>
                    <th className="pr-4">Citation rate</th>
                    <th className="pr-4">Answers</th>
                    <th>Strongest competitor</th>
                  </tr>
                </thead>
                <tbody>
                  {data.segments.map((segment) => {
                    const topCompetitor = Object.entries(segment.competitor_scores).sort(
                      (a, b) => b[1] - a[1],
                    )[0];
                    const gap = topCompetitor
                      ? Math.round((topCompetitor[1] - segment.brand_score) * 100) / 100
                      : null;
                    return (
                      <tr key={segment.segment} className="border-t border-[var(--border)]">
                        <td className="py-3 pr-4 font-medium">{humanize(segment.segment)}</td>
                        <td className="pr-4 tabular-nums">{segment.brand_score}</td>
                        <td className="pr-4 tabular-nums">
                          {Math.round(segment.mention_rate * 100)}%
                        </td>
                        <td className="pr-4 tabular-nums">
                          {Math.round(segment.citation_rate * 100)}%
                        </td>
                        <td className="pr-4 tabular-nums">{segment.result_count}</td>
                        <td>
                          {topCompetitor ? (
                            <span className="text-[var(--text-2)]">
                              {topCompetitor[0]}{" "}
                              <span className="tabular-nums text-[var(--text-2)]">
                                ({topCompetitor[1]}
                                {gap !== null && gap > 0 ? `, +${gap} ahead` : ""})
                              </span>
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
