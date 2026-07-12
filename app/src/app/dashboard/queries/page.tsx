import Link from "next/link";
import { apiFetch, type Me, type QueriesIntelPayload } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { LIKELIHOOD_COLORS, LIKELIHOOD_LABELS } from "@/lib/viz";

function ClassificationChip({
  classification,
}: {
  classification: { web_search_likelihood: string; signals: Record<string, number> } | null;
}) {
  if (!classification) {
    return <span className="text-xs text-slate-500">not classified yet</span>;
  }
  const bucket = classification.web_search_likelihood;
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-slate-200"
      title={`signals: ${JSON.stringify(classification.signals)}`}
    >
      <span
        className="inline-block h-2.5 w-2.5 rounded-full"
        style={{ background: LIKELIHOOD_COLORS[bucket] ?? "#64748b" }}
      />
      {LIKELIHOOD_LABELS[bucket] ?? bucket}
    </span>
  );
}

export default async function QueriesPage() {
  const [me, intel] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<QueriesIntelPayload>("/api/tenant/queries-intel"),
  ]);
  const queries = intel.data?.queries ?? [];

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Queries" isSuperadmin={me.data?.is_superadmin} />

      <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-1 text-sm font-medium text-slate-400">
          Query corpus · web-search likelihood · latest answers per surface and mode
        </h2>
        <p className="mb-4 text-xs text-slate-500">
          "Web search" is the dual-query diff: how much the AI's answer depends on live
          retrieval vs training. Mode A = provider API; Mode B (web interface) arrives M4.
        </p>
        {queries.length === 0 ? (
          <p className="text-sm text-slate-500">No queries configured.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-400">
                <tr>
                  <th className="py-2 pr-4">Query</th>
                  <th className="pr-4">Corpus</th>
                  <th className="pr-4">Web search</th>
                  <th className="pr-4">Brand in answer</th>
                  <th className="pr-4">Mode A (API)</th>
                  <th>Mode B (web)</th>
                </tr>
              </thead>
              <tbody>
                {queries.map((query) => {
                  const surfaces = Object.entries(query.latest_results);
                  return (
                    <tr key={query.id} className="border-t border-slate-800 align-top">
                      <td className="max-w-md py-3 pr-4">
                        {query.text}
                        {!query.active && (
                          <span className="ml-2 text-xs text-slate-500">(inactive)</span>
                        )}
                      </td>
                      <td className="pr-4 text-slate-400">{query.corpus_tag}</td>
                      <td className="pr-4">
                        <ClassificationChip classification={query.classification} />
                      </td>
                      <td className="pr-4">
                        {surfaces.length === 0 ? (
                          <span className="text-slate-500">—</span>
                        ) : surfaces.some(([, r]) => r.brand_mentioned) ? (
                          <span className="text-emerald-400">yes</span>
                        ) : (
                          <span className="text-amber-400">no</span>
                        )}
                      </td>
                      <td className="pr-4">
                        {surfaces.length === 0 ? (
                          <span className="text-xs text-slate-500">no results yet</span>
                        ) : (
                          <div className="flex flex-col gap-1">
                            {surfaces.map(([surface, result]) => (
                              <Link
                                key={surface}
                                href={`/dashboard/runs/${result.run_id}/results/${result.result_id}`}
                                className="text-xs text-indigo-400 hover:underline"
                              >
                                {surface} →
                              </Link>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="text-xs text-slate-600">M4</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
