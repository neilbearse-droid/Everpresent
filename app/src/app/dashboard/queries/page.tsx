import Link from "next/link";
import { apiFetch, rangeQuery, type Me, type QueriesIntelPayload } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { LIKELIHOOD_COLORS, LIKELIHOOD_LABELS, surfaceLabel, humanize } from "@/lib/viz";

function ClassificationChip({
  classification,
}: {
  classification: { web_search_likelihood: string; signals: Record<string, number> } | null;
}) {
  if (!classification) {
    return <span className="text-xs text-[var(--text-3)]">not classified yet</span>;
  }
  const bucket = classification.web_search_likelihood;
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-[var(--text)]"
      title={`signals: ${JSON.stringify(classification.signals)}`}
    >
      <span
        className="inline-block h-2.5 w-2.5 rounded-full"
        style={{ background: LIKELIHOOD_COLORS[bucket] ?? "var(--border-strong)" }}
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
    return <span className="text-xs text-[var(--text-3)]">no results yet</span>;
  }
  return (
    <div className="flex flex-col gap-1">
      {entries.map(([surface, result]) =>
        result.status === "ok" ? (
          <Link
            key={surface}
            href={`/dashboard/runs/${result.run_id}/results/${result.result_id}`}
            className="text-xs text-[var(--accent)] hover:underline"
          >
            {surfaceLabel(surface)}
          </Link>
        ) : (
          // A failed capture is missing data, not bad news about the brand:
          // quiet text, not the bad-news pill.
          <span key={surface} className="text-xs text-[var(--text-3)]">
            {surfaceLabel(surface)}: no answer
          </span>
        ),
      )}
    </div>
  );
}

export default async function QueriesPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, intel] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<QueriesIntelPayload>(`/api/tenant/queries-intel${rangeQuery(from, to)}`),
  ]);
  if (intel.status === 403) {
    return (
      <NoOrgNotice active="Queries" isSuperadmin={me.data?.is_superadmin} detail={intel.error} />
    );
  }
  const queries = intel.data?.queries ?? [];

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Queries" isSuperadmin={me.data?.is_superadmin} withDateRange />

      <section className="card p-4">
        <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
          Tracked queries and latest answers
        </h2>
        <p className="mb-4 text-xs text-[var(--text-3)]">
          Web search is how likely an engine is to search the web for a query instead of
          answering from memory, judged by comparing its answers with and without search. Answers
          come from two places: the engines&apos; developer APIs (more answers) and their public
          websites (closest to what people see). Compare puts the two side by side.
        </p>
        {queries.length === 0 ? (
          <p className="text-sm text-[var(--text-3)]">No queries configured.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm min-w-[760px]">
              <thead className="text-[var(--text-2)]">
                <tr>
                  <th className="py-2 pr-4">Query</th>
                  <th className="pr-4">Question set</th>
                  <th className="pr-4">Web search</th>
                  <th className="pr-4">Brand in answer</th>
                  <th className="pr-4">API answers</th>
                  <th className="pr-4">Website answers</th>
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
                        {query.branded && (
                          <span
                            className="chip ml-2 align-middle"
                            title="Branded query. Measured on the Brand tab and excluded from competitive visibility."
                          >
                            branded
                          </span>
                        )}
                        {!query.active && (
                          <span className="ml-2 text-xs text-[var(--text-3)]">(inactive)</span>
                        )}
                      </td>
                      <td className="pr-4 text-[var(--text-2)]">{humanize(query.corpus_tag)}</td>
                      <td className="pr-4">
                        <ClassificationChip classification={query.classification} />
                      </td>
                      <td className="pr-4">
                        {surfaces.length === 0 ? (
                          <span className="text-[var(--text-3)]">—</span>
                        ) : surfaces.some(([, r]) => r.brand_mentioned) ? (
                          <span className="text-[var(--pos)]">yes</span>
                        ) : (
                          <span className="text-[var(--warn-t)]">no</span>
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
                            className="text-xs text-[var(--accent)] hover:underline"
                          >
                            API vs website
                          </Link>
                        ) : (
                          <span className="text-xs text-[var(--text-3)]">—</span>
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
