import { apiFetch, type Me, type PersonasPayload } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { HBars } from "@/components/charts";
import { SERIES_COLORS } from "@/lib/viz";

export default async function PersonasPage() {
  const [me, personas] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<PersonasPayload>("/api/tenant/personas-intel"),
  ]);
  if (personas.status === 403) {
    return (
      <NoOrgNotice active="Personas" isSuperadmin={me.data?.is_superadmin} detail={personas.error} />
    );
  }
  const data = personas.data;

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Personas" isSuperadmin={me.data?.is_superadmin} />

      {!data || data.segments.length === 0 ? (
        <section className="card p-6">
          <h2 className="mb-2 text-lg font-medium">No persona data yet</h2>
          <p className="text-sm text-slate-400">
            Per-segment visibility appears after the first completed run.
            {personas.error ? ` (${personas.error})` : ""}
          </p>
        </section>
      ) : (
        <>
          <section className="mb-6 card p-6">
            <h2 className="mb-4 text-sm font-medium text-slate-400">
              Brand visibility by persona segment · {data.date}
            </h2>
            {/* Single measure across segments: one hue, no legend. */}
            <HBars
              items={data.segments.map((s) => ({
                label: s.segment,
                value: s.brand_score,
                color: SERIES_COLORS[0],
              }))}
            />
          </section>

          <section className="card p-6">
            <h2 className="mb-4 text-sm font-medium text-slate-400">
              Segment detail — where the gaps are
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-slate-400">
                  <tr>
                    <th className="py-2 pr-4">Segment</th>
                    <th className="pr-4">Brand score</th>
                    <th className="pr-4">Mention rate</th>
                    <th className="pr-4">Citation rate</th>
                    <th className="pr-4">Results</th>
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
                        <td className="py-3 pr-4 font-medium">{segment.segment}</td>
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
                            <span className="text-slate-300">
                              {topCompetitor[0]}{" "}
                              <span className="tabular-nums text-slate-400">
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
