import { apiFetch, rangeQuery, type CitationsPayload, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { AIOTile } from "@/components/aio-tile";
import { surfaceLabel } from "@/lib/viz";

const CATEGORY_STYLES: Record<string, string> = {
  brand: "bg-[var(--accent)] text-[var(--accent-ink)]",
  competitor: "bg-[var(--warn)] text-white",
  other: "bg-[var(--surface-2)] text-[var(--text)]",
};

export default async function CitationsPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, payload] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<CitationsPayload>(`/api/tenant/citations-intel${rangeQuery(from, to)}`),
  ]);
  if (payload.status === 403) {
    return (
      <NoOrgNotice active="Citations" isSuperadmin={me.data?.is_superadmin} detail={payload.error} />
    );
  }
  const data = payload.data;

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Citations" isSuperadmin={me.data?.is_superadmin} withDateRange />

      {!data ? (
        <p className="text-sm text-[var(--text-2)]">{payload.error}</p>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2">
            <AIOTile aio={data.aio} />
            <div className="card p-5">
              <div className="text-3xl font-semibold tabular-nums">
                {data.domains.filter((d) => d.category === "brand").length > 0 ? "Yes" : "No"}
              </div>
              <div className="mt-1 text-sm text-[var(--text-2)]">
                Your domains appear among the sources AI answers cite
              </div>
            </div>
          </div>

          {(data.power_pages ?? []).length > 0 && (
            <section className="card mb-6 p-6">
              <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
                Power Pages — the specific pages that feed your category's answers
              </h2>
              <p className="mb-4 text-xs text-[var(--text-3)]">
                Domains are trivia; pages are the battlefield. These URLs power the most
                answers across engines — getting onto (or beating) one high-influence page
                moves every answer it feeds.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-[var(--text-2)]">
                    <tr>
                      <th className="py-2 pr-4">Page</th>
                      <th className="pr-4">Owner</th>
                      <th className="pr-4">You named?</th>
                      <th className="pr-4">Queries fed</th>
                      <th className="pr-4">Citations</th>
                      <th>Engines</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.power_pages.slice(0, 15).map((p) => (
                      <tr key={p.url} className="border-t border-[var(--border)]">
                        <td className="max-w-md py-2.5 pr-4">
                          <a
                            href={p.url}
                            target="_blank"
                            rel="noreferrer"
                            className="block truncate font-mono text-xs text-[var(--accent)] hover:underline"
                            title={p.url}
                          >
                            {p.url.replace(/^https?:\/\//, "")}
                          </a>
                        </td>
                        <td className="pr-4">
                          <span
                            className={`rounded px-2 py-0.5 text-xs font-medium ${
                              CATEGORY_STYLES[p.category] ?? CATEGORY_STYLES.other
                            }`}
                          >
                            {p.category === "brand"
                              ? "yours"
                              : p.category === "competitor"
                                ? "rival"
                                : "third party"}
                          </span>
                        </td>
                        <td className="pr-4 text-xs">
                          {p.category !== "other" ? (
                            <span className="text-[var(--text-3)]">—</span>
                          ) : p.on_page === null ? (
                            <span className="text-[var(--text-3)]" title="Not crawled yet">
                              not crawled
                            </span>
                          ) : p.on_page ? (
                            <span
                              className="font-medium text-[var(--pos)]"
                              title={
                                p.competitors_on_page.length
                                  ? `Also names: ${p.competitors_on_page.join(", ")}`
                                  : "You're named; no rivals detected"
                              }
                            >
                              ✓ named
                            </span>
                          ) : (
                            <span
                              className="font-medium text-[var(--neg)]"
                              title={
                                p.competitors_on_page.length
                                  ? `Names ${p.competitors_on_page.join(", ")} — not you. Pitch this page.`
                                  : "Neither you nor tracked rivals are named"
                              }
                            >
                              ✗ absent
                            </span>
                          )}
                        </td>
                        <td className="pr-4 tabular-nums">{p.queries}</td>
                        <td className="pr-4 tabular-nums">{p.citations}</td>
                        <td className="text-xs text-[var(--text-2)]">
                          {p.surfaces.map(surfaceLabel).join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {Object.keys(data.source_types_by_engine ?? {}).length > 0 && (
            <section className="card mb-6 p-6">
              <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
                What each engine cites — source-type mix
              </h2>
              <p className="mb-4 text-xs text-[var(--text-3)]">
                Engines draw from different kinds of sources: ChatGPT leans encyclopedia and
                publishers, Perplexity and AI Overviews lean community (Reddit). Match your
                earned-media effort to where each engine actually looks.
              </p>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(data.source_types_by_engine).map(([surface, types]) => {
                  const total = Object.values(types).reduce((a, b) => a + b, 0) || 1;
                  return (
                    <div key={surface} className="card-inset p-3">
                      <div className="mb-2 text-sm font-medium">{surfaceLabel(surface)}</div>
                      <div className="space-y-1">
                        {Object.entries(types).map(([type, count]) => (
                          <div key={type} className="flex items-center justify-between text-xs">
                            <span className="text-[var(--text-2)]">{type}</span>
                            <span className="tabular-nums text-[var(--text-3)]">
                              {Math.round((100 * count) / total)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {(data.consulted_domains ?? []).length > 0 && (
            <section className="card mb-6 p-6">
              <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
                Consulted but not cited — warm targets
              </h2>
              <p className="mb-4 text-xs text-[var(--text-3)]">
                The engines read these sources on the way to their answers but didn&apos;t
                cite them. They&apos;re already in the consideration set — earning a citation
                here is a shorter path than starting cold.
              </p>
              <div className="flex flex-wrap gap-2">
                {data.consulted_domains.slice(0, 20).map((d) => (
                  <span key={d.domain} className="chip" title={`${d.queries} queries`}>
                    <span className="font-mono">{d.domain}</span>
                    <span className="ml-1.5 text-[var(--text-3)]">·{d.count}</span>
                  </span>
                ))}
              </div>
            </section>
          )}

          <section className="card p-6">
            <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
              Domains AI answers cite in this vertical
            </h2>
            <p className="mb-4 text-xs text-[var(--text-3)]">
              Across all measured surfaces, including Google's AI Overview. Getting your
              brand into these sources is how you enter the answers.
            </p>
            {data.domains.length === 0 ? (
              <p className="text-sm text-[var(--text-3)]">No citations captured yet.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="text-[var(--text-2)]">
                  <tr>
                    <th className="py-2 pr-4">Domain</th>
                    <th className="pr-4">Category</th>
                    <th className="pr-4">Citations</th>
                    <th>Surfaces</th>
                  </tr>
                </thead>
                <tbody>
                  {data.domains.map((d) => (
                    <tr key={d.domain} className="border-t border-[var(--border)]">
                      <td className="py-2.5 pr-4 font-medium">{d.domain}</td>
                      <td className="pr-4">
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-medium ${
                            CATEGORY_STYLES[d.category] ?? CATEGORY_STYLES.other
                          }`}
                        >
                          {d.category || "other"}
                        </span>
                      </td>
                      <td className="pr-4 tabular-nums">{d.count}</td>
                      <td className="font-mono text-xs text-[var(--text-2)]">
                        {d.surfaces.map(surfaceLabel).join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </main>
  );
}
