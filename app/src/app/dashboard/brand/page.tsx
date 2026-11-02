import { apiFetch, rangeQuery, type BrandReport, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";

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
    return <NoOrgNotice active="Branded questions" isSuperadmin={me.data?.is_superadmin} detail={report.error} />;
  }
  const d = report.data;

  // The lead: whether the engines know you when asked by name, how they
  // frame you, and what they get wrong. Wrong facts come first.
  const negative = d?.sentiment?.negative ?? 0;
  const lead =
    !d?.observed
      ? {
          tells: "No branded questions measured yet.",
          act: "Ask your EverPresent contact to mark your branded questions.",
          tone: "neutral" as const,
        }
      : {
          tells:
            d.accuracy_issues > 0
              ? `Engines state ${d.accuracy_issues} wrong ${d.accuracy_issues === 1 ? "fact" : "facts"} about ${d.brand_name}.`
              : negative > 0
                ? `Engines describe ${d.brand_name} negatively ${negative} ${negative === 1 ? "time" : "times"} in ${d.measured} answers.`
                : `Asked by name, engines name ${d.brand_name} in ${d.presence_rate}% of answers.`,
          act:
            d.accuracy_issues > 0
              ? "Correct the page that taught each wrong fact."
              : negative > 0
                ? "Find the source each negative framing echoes."
                : d.presence_rate < 90
                  ? "Make the facts clearer on your own pages."
                  : "Nothing to fix.",
          href: d.accuracy_issues > 0 || d.presence_rate < 90 ? "/dashboard/recommendations" : undefined,
          hrefLabel: "Recommendations",
          tone: (d.accuracy_issues > 0 || negative > 0 ? "bad" : d.presence_rate >= 90 ? "good" : "neutral") as "good" | "bad" | "neutral",
        };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Branded questions" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      {!d?.observed ? null : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            <div className="card p-4">
              <p className="bp-label mb-2.5">Named, of {d.measured} answers</p>
              <div className="text-4xl font-semibold leading-none tabular-nums">
                {d.presence_rate}%
              </div>
            </div>
            <div className="card p-4">
              <p className="bp-label mb-2.5">Framing</p>
              <div className="mt-1 flex flex-wrap gap-3 text-sm">
                {Object.entries(d.sentiment).length === 0 ? (
                  <span className="text-[var(--text-3)]">—</span>
                ) : (
                  Object.entries(d.sentiment).map(([k, v]) => (
                    <span key={k} className={`tabular-nums ${k === "negative" && v > 0 ? "bp-neg" : ""}`} style={{ color: SENT_COLOR[k] ?? "var(--text-2)" }}>
                      {v} {k}
                    </span>
                  ))
                )}
              </div>
            </div>
            <div className="card p-4">
              <p className="bp-label mb-2.5">Wrong facts</p>
              <div className="text-4xl font-semibold leading-none tabular-nums"
                   >
                <span className={d.accuracy_issues > 0 ? "bp-neg" : ""}>{d.accuracy_issues}</span>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-4">
            {d.queries.map((q) => (
              <section key={q.query} className="card p-4">
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
                              <span className={s.sentiment === "negative" ? "bp-neg" : ""} style={{ color: SENT_COLOR[s.sentiment] ?? "var(--text-2)" }}>
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
                        {a.engine} states {a.subject} as “{a.stated}”. Correct: “{a.expected}”.
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
