import { apiFetch, type ActionPlan, type InterventionsReport, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { surfaceLabel } from "@/lib/viz";
import { MarkShipped } from "./mark-shipped";

const DIAG_STYLE: Record<string, string> = {
  content_gap: "border-amber-500/40 bg-amber-500/5",
  knowledge_gap: "border-red-500/40 bg-red-500/5",
  undetermined: "border-[var(--border)] bg-[var(--surface-2)]",
};
const DIAG_CHIP: Record<string, string> = {
  content_gap: "text-[var(--warn-t)]",
  knowledge_gap: "text-[var(--neg)]",
  undetermined: "text-[var(--text-2)]",
};

const CONTEST_CHIP: Record<string, string> = {
  "winnable now": "text-[var(--pos)]",
  contested: "text-[var(--warn-t)]",
  "locked in": "text-[var(--text-3)]",
  "needs history": "text-[var(--text-3)]",
};

export default async function ActionPlanPage() {
  const [me, plan, proof] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<ActionPlan>("/api/tenant/action-plan"),
    apiFetch<InterventionsReport>("/api/tenant/interventions"),
  ]);
  if (plan.status === 403) {
    return <NoOrgNotice active="Action Plan" isSuperadmin={me.data?.is_superadmin} detail={plan.error} />;
  }
  const data = plan.data;
  const targets = data?.targets ?? [];
  const briefs = data?.briefs ?? [];

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Action Plan" isSuperadmin={me.data?.is_superadmin} />

      {targets.length === 0 && briefs.length === 0 ? (
        <section className="card p-6">
          <h2 className="mb-2 text-lg font-medium">Nothing to action yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Once a run finds visibility gaps, this tab turns each one into a source target
            list and a ready-to-work content brief.
          </p>
        </section>
      ) : (
        <div className="space-y-8">
          {/* #4 — Citation-gap target list */}
          <section className="card p-6">
            <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
              Source targets — where the AIs get their answers in your vertical
            </h2>
            <p className="mb-4 text-xs text-[var(--text-3)]">
              Third-party domains that AI answers cite alongside your competitors — but not
              you. Getting {data!.brand_name} covered on these is the highest-leverage way to
              enter the answers. Rivals' own sites and your own domains are excluded.
            </p>
            {targets.length === 0 ? (
              <p className="text-sm text-[var(--text-3)]">No third-party source gaps found.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-[var(--text-2)]">
                    <tr>
                      <th className="py-2 pr-4">Source domain</th>
                      <th className="pr-4">Cites a rival</th>
                      <th className="pr-4">Queries</th>
                      <th className="pr-4">Seen on</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {targets.map((t) => (
                      <tr key={t.domain} className="border-t border-[var(--border)]">
                        <td className="py-2 pr-4">
                          <a
                            href={t.example_url}
                            target="_blank"
                            rel="noreferrer"
                            className="font-mono text-[var(--accent)] hover:underline"
                          >
                            {t.domain}
                          </a>
                        </td>
                        <td className="pr-4 tabular-nums">{t.competitor_assoc}×</td>
                        <td className="pr-4 tabular-nums">{t.queries}</td>
                        <td className="pr-4 text-xs text-[var(--text-2)]">
                          {t.surfaces.map(surfaceLabel).join(", ")}
                        </td>
                        <td>
                          {t.already_citing_you ? (
                            <span className="text-[var(--pos)]">already cites you</span>
                          ) : (
                            <span className="text-[var(--warn-t)]">target</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Lost-Citation Radar — protect what you've already won */}
          {data!.protect?.ready && (
            <section className="card p-6">
              <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
                Protect — your pages losing citations
              </h2>
              <p className="mb-3 text-xs text-[var(--text-3)]">
                Run-over-run diff of your own cited pages. Losing a citation is the earliest
                decay signal — the proven fix is a cheap refresh: update the page's dates,
                stats, and examples.
              </p>
              <div className="mb-4 flex flex-wrap gap-2 text-xs">
                <span className="chip text-[var(--pos)]">{data!.protect.held} held</span>
                {data!.protect.gained > 0 && (
                  <span className="chip text-[var(--pos)]">{data!.protect.gained} gained</span>
                )}
                <span
                  className={`chip ${data!.protect.lost.length ? "text-[var(--neg)]" : ""}`}
                >
                  {data!.protect.lost.length} losing ground
                </span>
              </div>
              {data!.protect.lost.length === 0 ? (
                <p className="text-sm text-[var(--pos)]">
                  No lost citations since the previous run — your cited pages are holding.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="text-[var(--text-2)]">
                      <tr>
                        <th className="py-2 pr-4">Your page</th>
                        <th className="pr-4">Lost its citation on</th>
                        <th>Still cited on</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data!.protect.lost.map((entry) => (
                        <tr key={entry.url} className="border-t border-[var(--border)]">
                          <td className="max-w-sm py-2.5 pr-4">
                            <a
                              href={entry.url}
                              target="_blank"
                              rel="noreferrer"
                              className="block truncate font-mono text-xs text-[var(--accent)] hover:underline"
                              title={entry.url}
                            >
                              {entry.url.replace(/^https?:\/\//, "")}
                            </a>
                          </td>
                          <td className="pr-4 text-xs text-[var(--text-2)]">
                            {entry.queries.join(" · ")}
                          </td>
                          <td className="tabular-nums text-xs">
                            {entry.still_cited_on > 0 ? (
                              `${entry.still_cited_on} ${entry.still_cited_on === 1 ? "query" : "queries"}`
                            ) : (
                              <span className="text-[var(--neg)]">nothing — fully dropped</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {/* #1 — Content briefs */}
          <section>
            <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
              Content briefs — one per gap, ready to hand to a writer
            </h2>
            <p className="mb-3 text-xs text-[var(--text-3)]">
              Each gap query, turned into a brief: what to write, who's beating you, which
              sources to earn, and the questions to cover so AI answer engines can cite it.
              Ordered by contestability — answer churn × search-dependence — so effort goes
              where the answer is still in play.
            </p>
            {data!.strike_zone && (
              <div className="mb-4 flex flex-wrap gap-2 text-xs">
                {(["winnable now", "contested", "locked in", "needs history"] as const)
                  .filter((k) => data!.strike_zone[k])
                  .map((k) => (
                    <span
                      key={k}
                      className={`rounded-full border border-[var(--border)] px-2.5 py-1 font-medium ${CONTEST_CHIP[k] ?? ""}`}
                    >
                      {data!.strike_zone[k]} {k}
                    </span>
                  ))}
              </div>
            )}
            <div className="space-y-5">
              {briefs.map((b) => (
                <article
                  key={b.query_id}
                  className={`rounded-lg border p-5 ${DIAG_STYLE[b.diagnosis.type] ?? DIAG_STYLE.undetermined}`}
                >
                  <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-base font-medium">{b.query}</h3>
                    <span className="flex items-center gap-2 text-xs font-medium">
                      {b.contestability && (
                        <span
                          className={CONTEST_CHIP[b.contestability.label] ?? "text-[var(--text-3)]"}
                          title={
                            b.contestability.score === null
                              ? "Needs at least two runs of history to score"
                              : `Answer churn ${b.contestability.volatility} × search-dependence ${b.contestability.dependence}`
                          }
                        >
                          {b.contestability.score !== null && `${b.contestability.score} · `}
                          {b.contestability.label}
                        </span>
                      )}
                      <span className={DIAG_CHIP[b.diagnosis.type] ?? ""}>
                        {b.diagnosis.label} · {b.corpus_tag}
                      </span>
                    </span>
                  </div>
                  <p className="mb-4 text-sm text-[var(--text-2)]">{b.diagnosis.fix}</p>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="mb-1 text-xs font-medium text-[var(--text-2)]">Why it matters</div>
                      <ul className="space-y-1 text-sm text-[var(--text-2)]">
                        <li>
                          Missing on:{" "}
                          <span className="text-[var(--warn-t)]">
                            {b.engines_missing.join(", ") || "—"}
                          </span>
                        </li>
                        <li>
                          Winning instead:{" "}
                          <span className="text-[var(--text)]">
                            {b.competitors_winning.join(", ") || "no clear rival"}
                          </span>
                        </li>
                      </ul>
                      <div className="m-1 mt-3 mb-1 text-xs font-medium text-[var(--text-2)]">
                        Earn a citation on
                      </div>
                      {b.target_sources.length === 0 ? (
                        <p className="text-sm text-[var(--text-3)]">No specific source yet.</p>
                      ) : (
                        <ul className="space-y-1 text-sm">
                          {b.target_sources.map((s) => (
                            <li key={s.domain}>
                              <span className="font-mono text-[var(--accent)]">{s.domain}</span>
                              <span className="ml-2 text-xs text-[var(--text-3)]">
                                cites {s.rivals.join(", ")}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div>
                      <div className="mb-1 text-xs font-medium text-[var(--text-2)]">Suggested outline</div>
                      <ul className="space-y-1 text-sm text-[var(--text-2)]">
                        {b.outline.map((line, i) => (
                          <li key={i} className="text-xs">
                            {line}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  {b.citability?.ready && (
                    <div className="mt-4 border-t border-[var(--border)] pt-3">
                      <div className="mb-1.5 text-xs font-medium text-[var(--text-2)]">
                        Citability diff — copy the winning fingerprint
                      </div>
                      <div className="mb-2 flex flex-wrap gap-1.5 text-[11px]">
                        {b.citability.spec?.json_ld && <span className="chip">JSON-LD</span>}
                        {b.citability.spec?.faq_schema && <span className="chip">FAQ schema</span>}
                        {b.citability.spec?.has_tables && <span className="chip">comparison tables</span>}
                        {(b.citability.spec?.recent_year_mentions ?? 0) >= 3 && (
                          <span className="chip">
                            ~{b.citability.spec!.recent_year_mentions} fresh-date mentions
                          </span>
                        )}
                        <span className="chip">~{b.citability.spec?.word_count} words</span>
                        {b.citability.your_page && (
                          <a
                            href={b.citability.your_page.url}
                            target="_blank"
                            rel="noreferrer"
                            className="chip text-[var(--accent)] hover:underline"
                            title={b.citability.your_page.url}
                          >
                            your page ↗
                          </a>
                        )}
                      </div>
                      <ul className="space-y-1 text-xs text-[var(--text-2)]">
                        {b.citability.gaps?.map((gap, i) => (
                          <li key={i} className="flex gap-2">
                            <span aria-hidden className="text-[var(--warn-t)]">▲</span>
                            {gap}
                          </li>
                        ))}
                      </ul>
                      <p className="mt-1.5 text-[10px] text-[var(--text-3)]">
                        Spec drawn from {b.citability.winners?.length} crawled winning page
                        {(b.citability.winners?.length ?? 0) > 1 ? "s" : ""} cited on this query.
                      </p>
                    </div>
                  )}

                  <MarkShipped queryText={b.query} intervention={b.intervention ?? null} />
                </article>
              ))}
            </div>
          </section>

          {/* Proof — the fix→proof loop */}
          {(proof.data?.interventions.length ?? 0) > 0 && (
            <section className="card p-6">
              <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
                Proof — did the shipped fixes move the needle?
              </h2>
              <p className="mb-4 text-xs text-[var(--text-3)]">
                Brand presence on each fixed query, before vs after its ship date — with the
                same-window change on untouched queries as the control, so lift beats tide.
              </p>
              {proof.data!.aggregate && (
                <div className="mb-4 flex flex-wrap gap-2 text-xs">
                  <span className="chip">
                    {proof.data!.aggregate.measured} measured
                  </span>
                  <span
                    className={`chip ${proof.data!.aggregate.avg_delta >= 0 ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}
                  >
                    fixed queries {proof.data!.aggregate.avg_delta >= 0 ? "+" : ""}
                    {proof.data!.aggregate.avg_delta} pts
                  </span>
                  {proof.data!.aggregate.avg_control_delta !== null && (
                    <span className="chip">
                      untouched queries{" "}
                      {proof.data!.aggregate.avg_control_delta >= 0 ? "+" : ""}
                      {proof.data!.aggregate.avg_control_delta} pts
                    </span>
                  )}
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-[var(--text-2)]">
                    <tr>
                      <th className="py-2 pr-4">Query</th>
                      <th className="pr-4">Shipped</th>
                      <th className="pr-4">Presence before → after</th>
                      <th className="pr-4">Lift vs control</th>
                      <th>Newly visible on</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proof.data!.interventions.map((iv) => (
                      <tr key={iv.id} className="border-t border-[var(--border)] align-top">
                        <td className="max-w-xs py-2.5 pr-4">
                          {iv.query}
                          {iv.url && (
                            <a
                              href={iv.url}
                              target="_blank"
                              rel="noreferrer"
                              className="ml-2 text-xs text-[var(--accent)] hover:underline"
                            >
                              fix ↗
                            </a>
                          )}
                        </td>
                        <td className="pr-4 text-xs tabular-nums text-[var(--text-2)]">
                          {iv.shipped_at}
                        </td>
                        {iv.awaiting ? (
                          <td colSpan={3} className="text-xs text-[var(--text-3)]">
                            Awaiting post-ship runs — measurement starts with the next run.
                          </td>
                        ) : (
                          <>
                            <td className="pr-4 text-xs tabular-nums">
                              {iv.before_rate ?? "—"}% → {iv.after_rate ?? "—"}%
                            </td>
                            <td className="pr-4 text-xs tabular-nums">
                              <span
                                className={
                                  (iv.delta ?? 0) > 0
                                    ? "font-medium text-[var(--pos)]"
                                    : "text-[var(--text-2)]"
                                }
                              >
                                {(iv.delta ?? 0) >= 0 ? "+" : ""}
                                {iv.delta} pts
                              </span>
                              {iv.control_delta !== null && (
                                <span className="ml-1.5 text-[var(--text-3)]">
                                  (control {iv.control_delta >= 0 ? "+" : ""}
                                  {iv.control_delta})
                                </span>
                              )}
                            </td>
                            <td className="text-xs text-[var(--text-2)]">
                              {iv.newly_visible.length
                                ? iv.newly_visible.map(surfaceLabel).join(", ")
                                : "—"}
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </main>
  );
}
