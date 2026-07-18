import { apiFetch, rangeQuery, type EngineScorecard, type Me, type RoutingReport } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { HBars } from "@/components/charts";
import { surfaceLabel } from "@/lib/viz";

const DIAGNOSIS_ORDER = ["knowledge_gap", "content_gap", "undetermined", "visible"];
const DIAGNOSIS_STYLE: Record<string, { chip: string; dot: string }> = {
  visible: { chip: "text-[var(--pos)]", dot: "bg-emerald-400" },
  content_gap: { chip: "text-[var(--warn-t)]", dot: "bg-amber-400" },
  knowledge_gap: { chip: "text-[var(--neg)]", dot: "bg-red-400" },
  undetermined: { chip: "text-[var(--text-2)]", dot: "bg-slate-500" },
};

const CELL_STYLE: Record<string, string> = {
  brand: "bg-[var(--accent)] text-[var(--accent-ink)]",
  competitor: "bg-[var(--warn)] text-white",
  absent: "bg-[var(--surface-2)] text-[var(--text-3)]",
};
const CELL_LABEL: Record<string, string> = { brand: "You", competitor: "Rival", absent: "—" };

export default async function EnginesPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, card, routing] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<EngineScorecard>(`/api/tenant/engine-scorecard${rangeQuery(from, to)}`),
    apiFetch<RoutingReport>(`/api/tenant/routing${rangeQuery(from, to)}`),
  ]);
  if (card.status === 403) {
    return <NoOrgNotice active="Engines" isSuperadmin={me.data?.is_superadmin} detail={card.error} />;
  }
  const data = card.data;
  const engines = data?.engines ?? [];
  const matrix = data?.matrix ?? [];
  const surfaces = engines.map((e) => e.surface);
  const summary = data?.diagnosis_summary ?? {};

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Engines" isSuperadmin={me.data?.is_superadmin} withDateRange />

      {routing.data?.observed && (
        <section className="mb-6 card p-6">
          <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
            Do your prompts even trigger search?
          </h2>
          <p className="mb-4 text-xs text-[var(--text-3)]">
            Retrieval optimization only pays off for prompts the engine actually searches —
            the rest are answered from training, where only broad brand presence moves the
            needle. Share of priority prompts that triggered live search, per engine.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {routing.data.engines.map((e) => (
              <div key={e.surface} className="card-inset p-4">
                <div className="text-3xl font-semibold tabular-nums text-[var(--text)]">
                  {e.search_rate}%
                </div>
                <div className="mt-1 text-sm text-[var(--text-2)]">{surfaceLabel(e.surface)}</div>
                <div className="text-xs text-[var(--text-3)]">
                  {e.searched}/{e.measured} prompts searched
                  {e.from_probe ? " · natural probe" : ""}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {engines.length === 0 ? (
        <section className="card p-6">
          <h2 className="mb-2 text-lg font-medium">No engine data yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Cross-engine analysis appears after a completed run. Enable more than one engine
            in the admin panel to compare them.
          </p>
        </section>
      ) : (
        <>
          {/* Per-engine visibility */}
          <section className="mb-6 card p-6">
            <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
              Where {data!.brand_name} shows up, by engine
            </h2>
            <p className="mb-4 text-xs text-[var(--text-3)]">
              Share of measured queries where your brand appears in the answer — per answer
              engine. A low bar on one engine is where to focus.
            </p>
            <HBars
              items={engines.map((e) => ({
                label: `${surfaceLabel(e.surface)} · ${e.brand_present}/${e.queries_measured}`,
                value: e.brand_rate,
                color: "#34d399",
              }))}
              max={100}
              unit="%"
            />
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {engines.map((e) => (
                <div key={e.surface} className="rounded-md border border-[var(--border)] p-3 text-sm">
                  <div className="font-medium">{surfaceLabel(e.surface)}</div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">{e.brand_rate}%</div>
                  <div className="text-xs text-[var(--text-3)]">mentioned</div>
                  <div className="mt-1.5 flex items-baseline gap-1.5">
                    <span className="text-sm font-semibold tabular-nums text-[var(--text-2)]">
                      {e.citation_rate}%
                    </span>
                    <span className="text-xs text-[var(--text-3)]">cited (linked)</span>
                  </div>
                  {e.mention_citation_gap >= 10 && (
                    <div className="mt-1 text-xs text-[var(--warn-t)]">
                      named but not linked — {e.mention_citation_gap}pt gap
                    </div>
                  )}
                  <div className="mt-1 text-xs text-[var(--text-3)]">
                    {e.top_competitor
                      ? `Top rival cited: ${e.top_competitor}`
                      : "No rival cited"}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Diagnosis summary */}
          <section className="mb-6 card p-6">
            <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">Why you're missing</h2>
            <p className="mb-4 text-xs text-[var(--text-3)]">
              For every query where you're absent, the search-vs-training diff tells us the
              cause — and the cause dictates the fix.
            </p>
            <div className="flex flex-wrap gap-3">
              {DIAGNOSIS_ORDER.filter((t) => summary[t]).map((t) => (
                <div
                  key={t}
                  className="flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-sm"
                >
                  <span className={`h-2.5 w-2.5 rounded-full ${DIAGNOSIS_STYLE[t].dot}`} />
                  <span className="font-semibold tabular-nums">{summary[t]}</span>
                  <span className="text-[var(--text-2)]">
                    {t === "visible" ? "visible" : t.replace("_", " ")}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Query × engine matrix with diagnosis */}
          <section className="card p-6">
            <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
              Query × engine — who appears in each answer
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-[var(--text-2)]">
                  <tr>
                    <th className="py-2 pr-4">Query</th>
                    {surfaces.map((s) => (
                      <th key={s} className="px-2 text-center text-xs">
                        {surfaceLabel(s)}
                      </th>
                    ))}
                    <th className="pl-4">Diagnosis &amp; fix</th>
                  </tr>
                </thead>
                <tbody>
                  {matrix.map((row) => (
                    <tr key={row.id} className="border-t border-[var(--border)] align-top">
                      <td className="max-w-xs py-3 pr-4">{row.query}</td>
                      {surfaces.map((s) => {
                        const cell = row.cells[s];
                        return (
                          <td key={s} className="px-2 py-3 text-center">
                            <span
                              title={cell?.competitors?.length ? cell.competitors.join(", ") : ""}
                              className={`inline-block min-w-12 rounded px-2 py-0.5 text-xs ${
                                CELL_STYLE[cell?.state ?? "absent"]
                              }`}
                            >
                              {CELL_LABEL[cell?.state ?? "absent"]}
                            </span>
                          </td>
                        );
                      })}
                      <td className="pl-4">
                        <div className={`flex items-center gap-1.5 text-xs font-medium ${(DIAGNOSIS_STYLE[row.diagnosis.type] ?? DIAGNOSIS_STYLE.undetermined).chip}`}>
                          <span className={`h-2 w-2 rounded-full ${(DIAGNOSIS_STYLE[row.diagnosis.type] ?? DIAGNOSIS_STYLE.undetermined).dot}`} />
                          {row.diagnosis.label}
                        </div>
                        {row.diagnosis.type !== "visible" && (
                          <p className="mt-1 max-w-md text-xs text-[var(--text-2)]">{row.diagnosis.fix}</p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 text-xs text-[var(--text-3)]">
              <span className="text-[var(--pos)]">You</span> = your brand named ·{" "}
              <span className="text-[var(--warn-t)]">Rival</span> = a competitor named, you absent
              (hover for names) · — = neither. Diagnosis uses the training-only baseline where
              available.
            </p>
          </section>
        </>
      )}
    </main>
  );
}
