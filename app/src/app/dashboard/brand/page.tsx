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
          tells: "No branded questions are measured yet. These ask the engines about you by name, so they show how you're described and what's wrong, instead of whether you're named.",
          act: "Ask your EverPresent contact to mark the questions that name your brand as branded. They're then kept out of the visibility score and measured here from the next run.",
          tone: "neutral" as const,
        }
      : {
          tells: (
            <>
              Asked about {d.brand_name} by name, the engines name you in {d.presence_rate}% of {d.measured}{" "}
              {d.measured === 1 ? "answer" : "answers"}, state {d.accuracy_issues} wrong{" "}
              {d.accuracy_issues === 1 ? "fact" : "facts"}
              {negative > 0 ? <> and describe you negatively {negative} {negative === 1 ? "time" : "times"}</> : null}.
            </>
          ),
          act:
            d.accuracy_issues > 0
              ? "Fix the wrong facts first. Each one below names the engine, what it said and what's true; correct the page that taught it, usually your own. The Recommendations list has them as items."
              : negative > 0
                ? "Read the negative framings below and find the source they echo, usually a review site or an old article. Fresh third-party coverage is what changes how an engine describes you."
                : d.presence_rate < 90
                  ? "Some engines don't know you by name. The Recommendations list says which pages to make the facts clearer on."
                  : "Nothing to fix. The engines know you and describe you fairly; check back after a model change.",
          href: d.accuracy_issues > 0 || d.presence_rate < 90 ? "/dashboard/recommendations" : undefined,
          hrefLabel: "Recommendations",
          tone: (d.accuracy_issues > 0 || negative > 0 ? "bad" : d.presence_rate >= 90 ? "good" : "neutral") as "good" | "bad" | "neutral",
        };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Branded questions" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      <div className="mb-6">
        <h1 className="text-[26px] font-semibold tracking-tight">
          What the models say about {d?.brand_name ?? "your brand"}
        </h1>
        <details className="mt-2 max-w-3xl text-sm text-[var(--text-2)]">
          <summary className="cursor-pointer text-[12.5px] font-medium text-[var(--text-3)] hover:text-[var(--text-2)]">
            Why these are measured apart from the visibility score
          </summary>
          <p className="mt-2">
            Branded questions ask the engines about you by name. You&apos;d appear in
            almost every answer, so they&apos;re kept out of the visibility score and
            measured here instead: whether the answers name you, how they describe
            you, and what they get wrong.
          </p>
        </details>
      </div>

      {!d?.observed ? (
        <section className="card p-4">
          <h2 className="mb-2 text-lg font-medium">No branded questions measured yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Mark questions as <code>branded</code> in the setup to measure them here.
          </p>
        </section>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            <div className="card p-4">
              <p className="bp-label mb-2.5">Brand presence</p>
              <div className="text-4xl font-semibold leading-none tabular-nums">
                {d.presence_rate}%
              </div>
              <p className="mt-2.5 text-xs text-[var(--text-3)]">
                of {d.measured} branded answers name you
              </p>
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
              <p className="mt-2.5 text-xs text-[var(--text-3)]">sentiment of how you&apos;re described</p>
            </div>
            <div className="card p-4">
              <p className="bp-label mb-2.5">Accuracy issues</p>
              <div className="text-4xl font-semibold leading-none tabular-nums"
                   >
                <span className={d.accuracy_issues > 0 ? "bp-neg" : ""}>{d.accuracy_issues}</span>
              </div>
              <p className="mt-2.5 text-xs text-[var(--text-3)]">factual errors the models state about you</p>
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
