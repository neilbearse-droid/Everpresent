import { apiFetch, rangeQuery, type FanoutScorecardPayload, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";

export default async function FanoutPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, report] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<FanoutScorecardPayload>(`/api/tenant/fanout-scorecard${rangeQuery(from, to)}`),
  ]);
  if (report.status === 403) {
    return <NoOrgNotice active="Fan-out" isSuperadmin={me.data?.is_superadmin} detail={report.error} />;
  }
  const data = report.data;

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Fan-out" isSuperadmin={me.data?.is_superadmin} withDateRange />

      <div className="mb-5">
        <p className="eyebrow mb-1.5">Fan-out map</p>
        <h1 className="text-[26px] font-semibold tracking-tight">
          The sub-queries engines run before answering
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-2)]">
          A retrieval engine doesn&apos;t search your prompt — it fans it out into several
          sub-queries (&quot;shards&quot;) and competes each one separately. This is the map of that
          real contest surface: the shards each engine issued, and which of them explicitly name you
          or a competitor.
        </p>
      </div>

      <div className="card-inset mb-6 flex gap-3 p-4 text-xs text-[var(--text-2)]">
        <span aria-hidden className="mt-0.5 text-[var(--accent)]">ⓘ</span>
        <p className="leading-[1.55]">
          <span className="font-semibold text-[var(--text)]">What&apos;s measured here.</span>{" "}
          The shard list and &quot;names you / a competitor&quot; flags come straight from the shard
          text the engines exposed. Whether you appeared in the <em>final answer</em> is real,
          from mentions. Verified <span className="font-medium">per-shard presence</span> — winning
          or losing each individual shard — needs a deeper probe of every shard and arrives with the
          next phase; it is deliberately not claimed here. Branded prompts are excluded (they live in
          the Brand layer).
        </p>
      </div>

      {!data?.observed ? (
        <section className="card p-6">
          <h2 className="mb-2 text-lg font-medium">No fan-out captured yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Fan-out shows up where an engine exposes the sub-queries it issued (Gemini always;
            ChatGPT when present). Run a collection with a retrieval engine enabled and it appears
            here after processing.
          </p>
        </section>
      ) : (
        <div className="space-y-4">
          {data.prompts.map((p) => (
            <section key={p.query} className="card p-5">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-medium text-[var(--text)]">{p.query}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {Object.entries(p.reach_by_engine).map(([label, n]) => (
                      <span
                        key={label}
                        className="rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-2)]"
                      >
                        {label} · {n}
                      </span>
                    ))}
                    {p.contested > 0 && (
                      <span className="text-[11px] text-[var(--text-3)]">
                        {p.contested} name a competitor
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-display text-[22px] leading-none tracking-[-0.03em] tabular-nums">
                    {p.shards_total}
                  </div>
                  <div className="text-[11px] text-[var(--text-3)]">
                    shards · {p.engines_count} {p.engines_count === 1 ? "engine" : "engines"}
                  </div>
                  <span
                    className="mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
                    style={
                      p.brand_in_answer
                        ? { background: "rgba(20,122,74,.12)", color: "var(--pos)" }
                        : { background: "rgba(192,42,34,.1)", color: "var(--neg)" }
                    }
                  >
                    {p.brand_in_answer ? "✓ in final answer" : "✗ not in final answer"}
                  </span>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-[var(--text-3)]">
                      <th className="pb-2 pr-4 font-semibold">Shard</th>
                      <th className="pb-2 pr-4 font-semibold">Issued by</th>
                      <th className="pb-2 font-semibold">Names</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.shards.map((s) => (
                      <tr
                        key={s.text}
                        className="border-t border-[var(--border)] align-top"
                        style={
                          s.names_competitors.length && !s.names_brand
                            ? { background: "color-mix(in srgb, var(--neg) 4%, transparent)" }
                            : undefined
                        }
                      >
                        <td className="py-2.5 pr-4 text-[var(--text)]">{s.text}</td>
                        <td className="py-2.5 pr-4">
                          <div className="flex flex-wrap gap-1">
                            {s.engines.map((e) => (
                              <span
                                key={e}
                                className="rounded-full border border-[var(--border)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-2)]"
                              >
                                {e}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2.5">
                          <div className="flex flex-wrap gap-1">
                            {s.names_brand && (
                              <span
                                className="rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
                                style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                              >
                                you
                              </span>
                            )}
                            {s.names_competitors.map((c) => (
                              <span
                                key={c}
                                className="rounded-full px-2 py-0.5 text-[10.5px] font-medium"
                                style={{ background: "var(--surface-2)", color: "var(--text-2)" }}
                              >
                                {c}
                              </span>
                            ))}
                            {!s.names_brand && s.names_competitors.length === 0 && (
                              <span className="text-[var(--text-3)]">—</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}
    </main>
  );
}
