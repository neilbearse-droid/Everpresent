import Link from "next/link";
import { apiFetch, type Me, type QueriesIntelPayload } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { LIKELIHOOD_COLORS, LIKELIHOOD_LABELS, surfaceLabel } from "@/lib/viz";

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

function ModeLinks({
  entries,
}: {
  entries: [string, { result_id: number; run_id: number; status: string }][];
}) {
  if (entries.length === 0) {
    return <span className="text-xs text-slate-500">no results yet</span>;
  }
  return (
    <div className="flex flex-col gap-1">
      {entries.map(([surface, result]) =>
        result.status === "ok" ? (
          <Link
            key={surface}
            href={`/dashboard/runs/${result.run_id}/results/${result.result_id}`}
            className="text-xs text-indigo-400 hover:underline"
          >
            {surfaceLabel(surface)} →
          </Link>
        ) : (
          <span key={surface} className="text-xs text-red-400">
            {surfaceLabel(surface)}: error
          </span>
        ),
      )}
    </div>
  );
}

export default async function QueriesPage() {
  const [me, intel] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<QueriesIntelPayload>("/api/tenant/queries-intel"),
  ]);
  if (intel.status === 403) {
    return (
      <NoOrgNotice active="Queries" isSuperadmin={me.data?.is_superadmin} detail={intel.error} />
    );
  }
  const queries = intel.data?.queries ?? [];

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Queries" isSuperadmin={me.data?.is_superadmin} />

      <section className="card p-6">
        <h2 className="mb-1 text-sm font-medium text-slate-400">
          Query corpus · web-search likelihood · latest answers per surface and mode
        </h2>
        <p className="mb-4 text-xs text-slate-500">
          "Web search" is the dual-query diff: how much the AI's answer depends on live
          retrieval vs training. Mode A = provider API (volume); Mode B = the real consumer
          web interface (fidelity). Compare shows both answers side by side.
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
                  <th className="pr-4">Mode B (web)</th>
                  <th>Compare</th>
                </tr>
              </thead>
              <tbody>
                {queries.map((query) => {
                  const surfaces = Object.entries(query.latest_results);
                  const modeA = surfaces.filter(([, r]) => r.mode === "A");
                  const modeB = surfaces.filter(([, r]) => r.mode === "B");
                  const comparable =
                    modeA.find(([, r]) => r.status === "ok") &&
                    modeB.find(([, r]) => r.status === "ok");
                  return (
                    <tr key={query.id} className="border-t border-[var(--border)] align-top">
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
                        <ModeLinks entries={modeA} />
                      </td>
                      <td className="pr-4">
                        <ModeLinks entries={modeB} />
                      </td>
                      <td>
                        {comparable ? (
                          <Link
                            href={`/dashboard/compare?a=${
                              modeA.find(([, r]) => r.status === "ok")![1].result_id
                            }&b=${modeB.find(([, r]) => r.status === "ok")![1].result_id}`}
                            className="text-xs text-indigo-400 hover:underline"
                          >
                            A ⇄ B
                          </Link>
                        ) : (
                          <span className="text-xs text-slate-600">—</span>
                        )}
                      </td>
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
