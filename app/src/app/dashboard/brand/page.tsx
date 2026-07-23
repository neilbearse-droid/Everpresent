import { apiFetch, rangeQuery, type BrandReport, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";

const SENT_COLOR: Record<string, string> = {
  positive: "var(--pos)",
  neutral: "var(--text-3)",
  negative: "var(--neg)",
};

export default async function BrandPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, report] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<BrandReport>(`/api/tenant/brand${rangeQuery(from, to)}`),
  ]);
  if (report.status === 403) {
    return <NoOrgNotice active="Brand" isSuperadmin={me.data?.is_superadmin} detail={report.error} />;
  }
  const d = report.data;

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Brand" isSuperadmin={me.data?.is_superadmin} withDateRange />

      <div className="mb-6">
        <p className="eyebrow mb-1.5">Brand knowledge</p>
        <h1 className="text-[26px] font-semibold tracking-tight">
          What the models say about {d?.brand_name ?? "your brand"}
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-2)]">
          Branded queries ask the models directly about you — so they&apos;re kept
          out of the competitive visibility score (the brand almost always
          appears) and measured here instead. This is the source of truth for
          what the model knows: whether it still surfaces you, how it frames you,
          and where it&apos;s wrong.
        </p>
      </div>

      {!d?.observed ? (
        <section className="card p-6">
          <h2 className="mb-2 text-lg font-medium">No branded queries measured yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Flag queries as <code>branded</code> in the tenant config to populate this
            view — they&apos;re the ones designed to probe what the model knows about
            the brand.
          </p>
        </section>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            <div className="card p-5">
              <p className="eyebrow mb-2.5">Brand presence</p>
              <div className="text-4xl font-semibold leading-none tabular-nums">
                {d.presence_rate}%
              </div>
              <p className="mt-2.5 text-xs text-[var(--text-3)]">
                of {d.measured} branded answers name you — a drop here is an early warning
              </p>
            </div>
            <div className="card p-5">
              <p className="eyebrow mb-2.5">Framing</p>
              <div className="mt-1 flex flex-wrap gap-3 text-sm">
                {Object.entries(d.sentiment).length === 0 ? (
                  <span className="text-[var(--text-3)]">—</span>
                ) : (
                  Object.entries(d.sentiment).map(([k, v]) => (
                    <span key={k} className="tabular-nums" style={{ color: SENT_COLOR[k] ?? "var(--text-2)" }}>
                      {v} {k}
                    </span>
                  ))
                )}
              </div>
              <p className="mt-2.5 text-xs text-[var(--text-3)]">sentiment of how you&apos;re described</p>
            </div>
            <div className="card p-5">
              <p className="eyebrow mb-2.5">Accuracy issues</p>
              <div className="text-4xl font-semibold leading-none tabular-nums"
                   style={{ color: d.accuracy_issues > 0 ? "var(--neg)" : "var(--pos)" }}>
                {d.accuracy_issues}
              </div>
              <p className="mt-2.5 text-xs text-[var(--text-3)]">factual errors the models state about you</p>
            </div>
          </div>

          <div className="flex flex-col gap-4">
            {d.queries.map((q) => (
              <section key={q.query} className="card p-5">
                <h2 className="text-sm font-semibold text-[var(--text)]">{q.query}</h2>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-[var(--text-3)]">
                        <th className="pb-2 pr-4 font-medium">Engine</th>
                        <th className="pb-2 pr-4 font-medium">Names you</th>
                        <th className="pb-2 pr-4 font-medium">Framing</th>
                        <th className="pb-2 font-medium">What it says</th>
                      </tr>
                    </thead>
                    <tbody>
                      {q.surfaces.map((s) => (
                        <tr key={s.surface} className="border-t border-[var(--border)] align-top">
                          <td className="py-2.5 pr-4 text-[var(--text-2)]">{s.surface}</td>
                          <td className="py-2.5 pr-4">
                            {s.present ? (
                              <span className="text-[var(--pos)]">yes</span>
                            ) : (
                              <span className="text-[var(--neg)]">no</span>
                            )}
                          </td>
                          <td className="py-2.5 pr-4">
                            {s.sentiment ? (
                              <span style={{ color: SENT_COLOR[s.sentiment] ?? "var(--text-2)" }}>
                                {s.sentiment}
                              </span>
                            ) : (
                              <span className="text-[var(--text-3)]">—</span>
                            )}
                          </td>
                          <td className="py-2.5 text-xs italic text-[var(--text-2)]">
                            {s.snippet ? `“${s.snippet}”` : ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {q.accuracy.length > 0 && (
                  <div className="mt-3 border-t border-[var(--border)] pt-3">
                    {q.accuracy.map((a, i) => (
                      <p key={i} className="text-xs text-[var(--neg)]">
                        ⚠ {a.engine} states {a.subject} as “{a.stated}” — correct is “{a.expected}”.
                      </p>
                    ))}
                  </div>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
