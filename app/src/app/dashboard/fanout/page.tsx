import {
  apiFetch,
  rangeQuery,
  type FanoutReplay,
  type FanoutScorecardPayload,
  type Me,
} from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { Delta, EngineMark } from "@/components/ui";
import { AddToPlan } from "@/components/plan-buttons";
import { GenerateBrief } from "./generate-brief";
import { FanoutSimulator } from "./simulator";

// Why a sub-search has no measured presence: shown on hover so no cap is silent.
function unresolvedReason(status: string): string {
  switch (status) {
    case "dropped_k":
      return "Not re-checked: outside this plan's per-question limit for this run";
    case "dropped_ceiling":
      return "Not re-checked: this run's re-check limit was reached";
    case "withheld_cap":
      return "Not re-checked: the monthly spend cap was reached";
    case "error":
      return "The re-check failed";
    default:
      return "Not re-checked";
  }
}

export default async function FanoutPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, report, replay] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<FanoutScorecardPayload>(`/api/tenant/fanout-scorecard${rangeQuery(from, to)}`),
    apiFetch<FanoutReplay>(`/api/tenant/fanout-replay${rangeQuery(from, to)}`),
  ]);
  if (report.status === 403) {
    return <NoOrgNotice active="Sub-questions" isSuperadmin={me.data?.is_superadmin} detail={report.error} />;
  }
  const data = report.data;

  // The lead: how many of the engines' own sub-searches you're in, how many
  // urgent misses there are, and which direction it's moving.
  const prompts = data?.observed ? data.prompts : [];
  const sum = (f: (p: (typeof prompts)[number]) => number) => prompts.reduce((n, p) => n + f(p), 0);
  const shards = sum((p) => p.shards_total);
  const present = sum((p) => p.shards_present);
  const absent = sum((p) => p.shards_absent);
  const high = sum((p) => p.high_misses);
  const notInAnswer = prompts.filter((p) => !p.brand_in_answer).length;
  const topMiss = prompts
    .flatMap((p) => p.shards.map((sh) => ({ q: p.query, sh })))
    .find(({ sh }) => sh.priority === "high" && sh.source === "reprobed" && sh.brand_present === false);
  const lead =
    !data?.observed
      ? {
          tells: "No sub-searches captured yet.",
          act: "Nothing to do yet.",
          tone: "neutral" as const,
        }
      : {
          tells:
            present + absent > 0 ? (
              <>
                You appear in {present} of {present + absent} re-checked sub-searches
                {high > 0 ? <>, {high} high-priority {high === 1 ? "miss" : "misses"}</> : null}.
              </>
            ) : (
              <>
                {shards} sub-searches across {prompts.length} {prompts.length === 1 ? "question" : "questions"}
                {notInAnswer > 0 ? <>; you&apos;re out of {notInAnswer} final answers</> : null}.
              </>
            ),
          act: topMiss
            ? `Generate the brief for "${topMiss.sh.text}".`
            : absent > 0
              ? `Work the ${absent} remaining ${absent === 1 ? "miss" : "misses"} in priority order.`
              : present > 0
                ? "Hold what's winning."
                : data.reprobe_enabled
                  ? "Wait for the next re-check."
                  : "Ask your EverPresent contact to turn on re-checking.",
          tone: (high > 0 || (present + absent > 0 && absent > present) ? "bad" : present > 0 && absent === 0 ? "good" : "neutral") as "good" | "bad" | "neutral",
        };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Sub-questions" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      {replay.data && replay.data.prompts.length > 0 && <FanoutSimulator data={replay.data} />}


      {!data?.observed ? (
        <section className="card p-4">
          <p className="text-sm text-[var(--text-2)]">No sub-searches captured yet.</p>
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
                        className="inline-flex items-center gap-1.5 rounded-[4px] border border-[var(--border)] bg-[var(--surface-2)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-2)]"
                      >
                        <EngineMark surface={label} size={14} />
                        {label} · <span className="font-semibold text-[var(--text)]">{n}</span>
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
                        re-checked
                        {p.high_misses > 0 && (
                          <>
                            {" · "}
                            <span className="bp-neg">
                              {p.high_misses} high-priority miss{p.high_misses === 1 ? "" : "es"}
                            </span>
                          </>
                        )}
                        {p.won_back > 0 && (
                          <>
                            {" · "}
                            <Delta value={p.won_back} /> won back
                          </>
                        )}
                        {p.lost > 0 && (
                          <>
                            {" · "}
                            <Delta value={-p.lost} /> lost
                          </>
                        )}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-display text-[22px] leading-none tracking-[-0.03em] tabular-nums">
                    {p.shards_total}
                  </div>
                  <div className="text-[11px] text-[var(--text-3)]">
                    {p.shards_total === 1 ? "sub-search" : "sub-searches"} · {p.engines_count}{" "}
                    {p.engines_count === 1 ? "engine" : "engines"}
                  </div>
                  <span
                    className="mt-1.5 inline-flex items-center gap-1 rounded-[4px] px-2 py-0.5 text-[10.5px] font-semibold"
                    style={
                      p.brand_in_answer
                        ? { background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border)" }
                        : { background: "var(--ink)", color: "var(--ink-text)", border: "1px solid var(--ink)" }
                    }
                  >
                    {p.brand_in_answer ? "in final answer" : "not in final answer"}
                  </span>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[12px] text-[var(--text-3)]">
                      <th className="pb-2 pr-4 font-semibold">Sub-search</th>
                      <th className="pb-2 pr-4 font-semibold">Run by</th>
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
                        <td className="py-2.5 pr-4 font-medium text-[var(--text)]">
                          {s.text}
                          {/* Close the loop (M25c): a brief that answers the lost sub-search. */}
                          {s.priority === "high" && (
                            <div className="mt-2 flex flex-wrap items-start gap-2">
                              <AddToPlan
                                gapRef={`sub:${s.id ?? s.text}`}
                                title={`Win: ${s.text.split(" ").slice(0, 6).join(" ")}${s.text.split(" ").length > 6 ? "…" : ""}`}
                                actionText={`Publish a page that answers "${s.text}"${s.winners.length ? `; ${s.winners.join(", ")} win it today` : ""}.`}
                                link="/dashboard/fanout"
                                queryText={p.query}
                              />
                              {s.id !== null && <GenerateBrief shardId={s.id} />}
                            </div>
                          )}
                        </td>
                        <td className="py-2.5 pr-4">
                          <div className="flex flex-wrap gap-1">
                            {s.engines.map((e) => (
                              <span
                                key={e}
                                className="inline-flex items-center gap-1 rounded-[4px] border border-[var(--border)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-2)]"
                              >
                                <EngineMark surface={e} size={12} />
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
                                style={{ background: "var(--accent)", color: "var(--accent-ink)", border: "1px solid var(--accent)" }}
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
                              className={`text-[12px] font-bold ${s.brand_present ? "" : "bp-neg"}`}
                              title={`Re-checked on ${s.probe_engine ?? "an engine that ran it"}${s.probed_at ? ` · ${s.probed_at.slice(0, 10)}` : ""}`}
                            >
                              {s.brand_present ? "present" : "absent"}
                            </span>
                          ) : (
                            <span className="text-[11px] text-[var(--text-3)]" title={unresolvedReason(s.probe_status)}>
                              unresolved
                            </span>
                          )}
                          {s.trend === "won_back" && (
                            <div className="mt-0.5 text-[10.5px] font-semibold">▲ won back</div>
                          )}
                          {s.trend === "lost" && (
                            <div className="mt-0.5 text-[10.5px]"><span className="bp-neg">▼ lost</span></div>
                          )}
                        </td>
                        <td className="py-2.5 pr-4 text-[12px]">
                          {s.source === "reprobed" ? (
                            s.winners.length ? (
                              <span className="font-medium text-[var(--text)]">{s.winners.join(", ")}</span>
                            ) : (
                              <span className="text-[var(--text-3)]">—</span>
                            )
                          ) : (
                            ""
                          )}
                        </td>
                        <td className="py-2.5">
                          {s.priority && (
                            <span
                              className="rounded-[4px] px-2 py-0.5 text-[10.5px] font-semibold"
                              style={
                                s.priority === "high"
                                  ? { background: "var(--ink)", color: "var(--ink-text)", border: "1px solid var(--ink)" }
                                  : { background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border)" }
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
