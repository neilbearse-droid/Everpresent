import { apiFetch, rangeQuery, type FanoutScorecardPayload, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { GenerateBrief } from "./generate-brief";

// Why a shard has no measured presence — shown on hover so no cap is silent.
function unresolvedReason(status: string): string {
  switch (status) {
    case "dropped_k":
      return "Not re-probed: outside this plan's per-prompt limit this run";
    case "dropped_ceiling":
      return "Not re-probed: this run's re-probe limit was reached";
    case "withheld_cap":
      return "Not re-probed: the monthly spend cap was reached";
    case "error":
      return "The re-probe call failed";
    default:
      return "Not re-probed";
  }
}

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
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Fan-out" isSuperadmin={me.data?.is_superadmin} withDateRange />

      <div className="mb-5">
        <p className="eyebrow mb-1.5">Fan-out map</p>
        <h1 className="text-[26px] font-semibold tracking-tight">
          The sub-queries engines run before answering
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-2)]">
          Search-based engines don&apos;t search your prompt as written. They split it into several
          sub-queries and pick sources for each one. This page lists the sub-queries each engine
          ran, whether you appear in the results, and who does.
        </p>
      </div>

      <div className="card-inset mb-6 flex gap-3 p-4 text-xs text-[var(--text-2)]">
                <p className="leading-[1.55]">
          <span className="font-semibold text-[var(--text)]">What&apos;s measured here.</span>{" "}
          The shard list and &quot;names you / a competitor&quot; flags come straight from the shard
          text the engines exposed. Whether you appeared in the <em>final answer</em> is real,
          from mentions. <span className="font-medium">Per-shard presence</span> is shown only for
          shards we re-ran as their own query on an engine that issued them (&quot;re-probed&quot;);
          every other shard is marked unresolved rather than estimated from the full answer.
          Branded prompts are excluded (they live in the Brand layer).
          {data?.observed && (
            <>
              {" "}
              <span className="font-medium text-[var(--text)]">
                Coverage: {data.coverage.reprobed} re-probed · {data.coverage.unresolved} unresolved.
              </span>
              {(data.trend.won_back > 0 || data.trend.lost > 0) &&
                ` Since each shard's previous re-probe: ${data.trend.won_back} won back, ${data.trend.lost} newly lost.`}
              {!data.reprobe_enabled && " Re-probing is off for this account, so presence is not measured yet."}
            </>
          )}
        </p>
      </div>

      {!data?.observed ? (
        <section className="card p-4">
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
            <section key={p.query} className="card p-4">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-medium text-[var(--text)]">{p.query}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {Object.entries(p.reach_by_engine).map(([label, n]) => (
                      <span
                        key={label}
                        className="rounded-[4px] border border-[var(--border)] bg-[var(--surface-2)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-2)]"
                      >
                        {label} · {n}
                      </span>
                    ))}
                    {p.contested > 0 && (
                      <span className="text-[11px] text-[var(--text-3)]">
                        {p.contested} name a competitor
                      </span>
                    )}
                    {p.shards_present + p.shards_absent > 0 && (
                      <span className="text-[11px] font-medium text-[var(--text-2)]">
                        · you&apos;re in {p.shards_present} of {p.shards_present + p.shards_absent}{" "}
                        re-probed
                        {p.high_misses > 0 && (
                          <span className="text-[var(--neg)]"> · {p.high_misses} high-priority miss{p.high_misses === 1 ? "" : "es"}</span>
                        )}
                        {p.won_back > 0 && (
                          <span className="text-[var(--pos)]"> · ▲ {p.won_back} won back</span>
                        )}
                        {p.lost > 0 && <span className="text-[var(--neg)]"> · ▼ {p.lost} newly lost</span>}
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
                    className="mt-1.5 inline-flex items-center gap-1 rounded-[4px] px-2 py-0.5 text-[10.5px] font-semibold"
                    style={
                      p.brand_in_answer
                        ? { background: "var(--surface)", color: "var(--text)", border: "1.5px solid var(--line)" }
                        : { background: "var(--accent)", color: "var(--accent-ink)", border: "1.5px solid var(--line)" }
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
                      <th className="pb-2 pr-4 font-semibold">Names</th>
                      <th className="pb-2 pr-4 font-semibold">You</th>
                      <th className="pb-2 pr-4 font-semibold">Who won</th>
                      <th className="pb-2 font-semibold">Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.shards.map((s) => (
                      <tr
                        key={s.text}
                        className="border-t border-[var(--border)] align-top"
                        style={
                          s.priority === "high"
                            ? { background: "var(--hatch)" }
                            : undefined
                        }
                      >
                        <td className="py-2.5 pr-4 text-[var(--text)]">
                          {s.text}
                          {/* Close the loop (M25c): a brief that answers the lost shard. */}
                          {s.priority === "high" && s.id !== null && (
                            <div className="mt-2">
                              <GenerateBrief shardId={s.id} />
                            </div>
                          )}
                        </td>
                        <td className="py-2.5 pr-4">
                          <div className="flex flex-wrap gap-1">
                            {s.engines.map((e) => (
                              <span
                                key={e}
                                className="rounded-[4px] border border-[var(--border)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-2)]"
                              >
                                {e}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2.5 pr-4">
                          <div className="flex flex-wrap gap-1">
                            {s.names_brand && (
                              <span
                                className="rounded-[4px] px-2 py-0.5 text-[10.5px] font-semibold"
                                style={{ background: "var(--accent)", color: "var(--accent-ink)", border: "1.5px solid var(--line)" }}
                              >
                                you
                              </span>
                            )}
                            {s.names_competitors.map((c) => (
                              <span
                                key={c}
                                className="rounded-[4px] px-2 py-0.5 text-[10.5px] font-medium"
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
                        <td className="py-2.5 pr-4 whitespace-nowrap">
                          {s.source === "reprobed" ? (
                            <span
                              className="text-[12px] font-semibold"
                              style={{ color: s.brand_present ? "var(--pos)" : "var(--neg)" }}
                              title={`Re-probed on ${s.probe_engine ?? "an issuing engine"}${s.probed_at ? ` · ${s.probed_at.slice(0, 10)}` : ""}`}
                            >
                              {s.brand_present ? "✓ present" : "✗ absent"}
                            </span>
                          ) : (
                            <span className="text-[11px] text-[var(--text-3)]" title={unresolvedReason(s.probe_status)}>
                              unresolved
                            </span>
                          )}
                          {s.trend === "won_back" && (
                            <div className="mt-0.5 text-[10.5px] font-semibold text-[var(--pos)]">▲ won back</div>
                          )}
                          {s.trend === "lost" && (
                            <div className="mt-0.5 text-[10.5px] font-semibold text-[var(--neg)]">▼ newly lost</div>
                          )}
                        </td>
                        <td className="py-2.5 pr-4 text-[12px] text-[var(--text-2)]">
                          {s.source === "reprobed" ? (s.winners.length ? s.winners.join(", ") : "—") : ""}
                        </td>
                        <td className="py-2.5">
                          {s.priority && (
                            <span
                              className="rounded-[4px] px-2 py-0.5 text-[10.5px] font-semibold"
                              style={
                                s.priority === "high"
                                  ? { background: "var(--accent)", color: "var(--accent-ink)", border: "1.5px solid var(--line)" }
                                  : { background: "var(--surface)", color: "var(--text)", border: "1.5px solid var(--line)" }
                              }
                            >
                              {s.priority}
                            </span>
                          )}
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
