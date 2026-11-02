import { apiFetch, rangeQuery, type Me, type PersonasPayload } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { HBars } from "@/components/charts";
import { SERIES_COLORS, humanize } from "@/lib/viz";
import { Delta } from "@/components/ui";
import { AddToPlan } from "@/components/plan-buttons";

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
          tells: "No persona answers yet.",
          act: "Tick a persona against the questions that matter.",
          href: "/dashboard/queries",
          hrefLabel: "Queries",
          tone: "neutral" as const,
        }
      : {
          tells:
            behind.length > 0
              ? `${behind[0].rival} leads you with ${humanize(behind[0].segment)} by ${behind[0].gap}.`
              : `Strongest with ${humanize(best!.segment)}${segs.length > 1 ? `, weakest with ${humanize(worst!.segment)}` : ""}; no rival leads.`,
          act: behind.length > 0 ? `Write for what ${humanize(behind[0].segment)} asks about.` : "Nothing to fix by persona.",
          href: behind.length > 0 ? "/dashboard/action-plan" : undefined,
          hrefLabel: "Action Plan",
          tone: (behind.length === 0 ? "good" : behind.length >= segs.length ? "bad" : "neutral") as "good" | "bad" | "neutral",
        };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Personas" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      {!data || data.segments.length === 0 ? (
        personas.error ? <p className="text-sm text-[var(--text-3)]">{personas.error}</p> : null
      ) : (
        <>
          <section className="mb-6 card p-4">
            <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
              Score by persona · {data.date}
            </h2>
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
                    <th className="pr-4">Score</th>
                    <th className="pr-4">Named</th>
                    <th className="pr-4">Cited</th>
                    <th className="pr-4">Answers</th>
                    <th className="pr-4">Top rival</th>
                    <th></th>
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
                        <td className="py-3 pr-4 font-semibold">{humanize(segment.segment)}</td>
                        <td className="pr-4 font-semibold tabular-nums">{segment.brand_score}</td>
                        <td className="pr-4 text-xs tabular-nums text-[var(--text-2)]">
                          {Math.round(segment.mention_rate * 100)}%
                        </td>
                        <td className="pr-4 text-xs tabular-nums text-[var(--text-2)]">
                          {Math.round(segment.citation_rate * 100)}%
                        </td>
                        <td className="pr-4 text-xs tabular-nums text-[var(--text-2)]">{segment.result_count}</td>
                        <td className="pr-4">
                          {topCompetitor ? (
                            <span className="inline-flex items-center gap-2">
                              <span className="text-[var(--text-2)]">{topCompetitor[0]}</span>
                              <span className="text-xs tabular-nums text-[var(--text-3)]">{topCompetitor[1]}</span>
                              {gap !== null && gap !== 0 && <Delta value={-gap} digits={2} />}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-1.5 text-right">
                          {topCompetitor && gap !== null && gap > 0 && (
                            <AddToPlan
                              gapRef={`persona:${segment.segment}`}
                              title={`Win back ${humanize(segment.segment)}`}
                              actionText={`${topCompetitor[0]} leads you by ${gap} with ${humanize(segment.segment)}. Write for what this buyer asks about.`}
                              link="/dashboard/personas"
                            />
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
