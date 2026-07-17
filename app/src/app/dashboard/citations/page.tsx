import { apiFetch, type CitationsPayload, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { AIOTile } from "@/components/aio-tile";
import { surfaceLabel } from "@/lib/viz";

const CATEGORY_STYLES: Record<string, string> = {
  brand: "bg-emerald-700 text-white",
  competitor: "bg-amber-700 text-white",
  other: "bg-[var(--surface-2)] text-[var(--text)]",
};

export default async function CitationsPage() {
  const [me, payload] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<CitationsPayload>("/api/tenant/citations-intel"),
  ]);
  if (payload.status === 403) {
    return (
      <NoOrgNotice active="Citations" isSuperadmin={me.data?.is_superadmin} detail={payload.error} />
    );
  }
  const data = payload.data;

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Citations" isSuperadmin={me.data?.is_superadmin} />

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
