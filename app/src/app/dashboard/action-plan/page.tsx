import { apiFetch, type ActionPlan, type InterventionsReport, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { surfaceLabel } from "@/lib/viz";
import { Bullets, Delta, EngineMark, ExtLink, Linkify, shortUrl } from "@/components/ui";
import { AddToPlan } from "@/components/plan-buttons";
import { CONTROL_LABEL } from "@/lib/recs";
import { MarkShipped } from "./mark-shipped";

// Format a backend YYYY-MM-DD into the app's friendly date style, matching the
// runs table and date picker (§audit low). Parsed in local time so the day
// doesn't shift across the UTC boundary.
function fmtDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const DIAG_STYLE: Record<string, string> = {
  content_gap: "border-[var(--border)]",
  knowledge_gap: "border-[var(--border)]",
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

  // The lead: how many places to earn a citation, how many pages to write,
  // what you've lost, and the single highest-value move. Lost citations come
  // first (cheapest to win back), then a winnable brief, then a source target.
  const openTargets = targets.filter((t) => !t.already_citing_you);
  const lost = data?.protect?.ready ? data.protect.lost.length : 0;
  const winnable = data?.strike_zone?.["winnable now"] ?? 0;
  const firstWinnable = briefs.find((b) => b.contestability?.label === "winnable now") ?? briefs[0] ?? null;
  const topTarget = openTargets[0] ?? null;
  const lead =
    targets.length === 0 && briefs.length === 0
      ? {
          tells: "Nothing to act on yet.",
          act: "Nothing to write yet.",
          href: "/dashboard/recommendations",
          hrefLabel: "Recommendations",
          tone: "neutral" as const,
        }
      : {
          tells:
            lost > 0
              ? `${lost} of your ${lost === 1 ? "page" : "pages"} lost a citation since the last run.`
              : briefs.length > 0
                ? `${briefs.length} ${briefs.length === 1 ? "question needs" : "questions need"} a page${winnable > 0 ? `, ${winnable} winnable now` : ""}.`
                : openTargets.length > 0
                  ? `${openTargets.length} ${openTargets.length === 1 ? "site cites" : "sites cite"} your rivals and not you.`
                  : "Every tracked question names you.",
          act:
            lost > 0
              ? "Refresh those pages, then mark the fix shipped."
              : firstWinnable
                ? `Write the page for "${firstWinnable.query}" and mark it shipped.`
                : topTarget
                  ? `Get ${data!.brand_name} covered on ${topTarget.domain}.`
                  : "Hold what's winning.",
          href: lost > 0 ? undefined : topTarget && !firstWinnable ? topTarget.example_url : undefined,
          hrefLabel: "Open the site",
          tone: (lost > 0 ? "bad" : briefs.length === 0 && openTargets.length === 0 ? "good" : "neutral") as "good" | "bad" | "neutral",
        };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Action Plan" isSuperadmin={me.data?.is_superadmin} />
      <PageLead {...lead} />

      {targets.length === 0 && briefs.length === 0 ? null : (
        <div className="space-y-8">
          {/* #4 — Citation-gap target list */}
          <section className="card p-4">
            <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
              Sites that cite your rivals, not you
            </h2>
            <p className="mb-3 max-w-[75ch] text-[12.5px] text-[var(--text-3)]">
              Not a list to get onto. Each row says what kind of page it is and what is realistic
              there; the ones worth the effort are ranked under Recommendations.
            </p>
            {targets.length === 0 ? (
              <p className="text-sm text-[var(--text-3)]">No third-party source gaps found.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-[var(--text-2)]">
                    <tr>
                      <th className="py-2 pr-4">Site</th>
                      <th className="pr-4">Rival citations</th>
                      <th className="pr-4">Questions</th>
                      <th className="pr-4">Engines</th>
                      <th className="pr-4">What&apos;s realistic</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {targets.map((t) => (
                      <tr key={t.domain} className="border-t border-[var(--border)]">
                        <td className="py-2 pr-4 font-semibold">
                          <ExtLink href={t.example_url}>{t.domain}</ExtLink>
                        </td>
                        <td className="pr-4 tabular-nums">{t.competitor_assoc}×</td>
                        <td className="pr-4 tabular-nums text-[var(--text-2)]">{t.queries}</td>
                        <td className="pr-4">
                          <span className="flex gap-1">
                            {t.surfaces.map((x) => (
                              <span key={x} title={surfaceLabel(x)}>
                                <EngineMark surface={x} size={16} />
                              </span>
                            ))}
                          </span>
                        </td>
                        <td className="min-w-[16rem] py-2 pr-4 text-xs text-[var(--text-2)]">
                          <span className="font-semibold text-[var(--text)]">{t.kind_label}.</span>{" "}
                          {t.route}
                          <span className="ml-1 text-[var(--text-3)]">({CONTROL_LABEL[t.control]?.toLowerCase()})</span>
                        </td>
                        <td className="py-1.5 text-right">
                          {t.already_citing_you ? (
                            <span className="chip">cites you</span>
                          ) : (
                            <AddToPlan
                              gapRef={`target:${t.domain}`}
                              title={`${t.kind_label}: ${t.domain}`}
                              actionText={`${t.domain} is cited alongside your rivals ${t.competitor_assoc} times across ${t.queries} questions. ${t.route}.`}
                              link="/dashboard/action-plan"
                            />
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
            <section className="card p-4">
              <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">
                Your pages, since the last run
              </h2>
              <div className="mb-5 grid gap-3 sm:grid-cols-3">
                <div className="card-inset p-4">
                  <div className="text-3xl tabular-nums text-[var(--text)]">
                    <Delta value={data!.protect.gained} />
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-2)]">Gained</div>
                </div>
                <div className="card-inset p-4">
                  <div className="text-3xl font-semibold tabular-nums text-[var(--text)]">
                    {data!.protect.held}
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-2)]">Held</div>
                </div>
                <div className="card-inset p-4">
                  <div className="text-3xl tabular-nums text-[var(--text)]">
                    <Delta value={-data!.protect.lost.length} />
                  </div>
                  <div className="mt-1 text-sm text-[var(--text-2)]">Lost</div>
                </div>
              </div>
              {data!.protect.lost.length === 0 ? (
                <p className="text-sm text-[var(--text-2)]">No lost citations.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="text-[var(--text-2)]">
                      <tr>
                        <th className="py-2 pr-4">Your page</th>
                        <th className="pr-4">Lost on</th>
                        <th className="pr-4">Still cited</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {data!.protect.lost.map((entry) => (
                        <tr key={entry.url} className="border-t border-[var(--border)]">
                          <td className="py-2.5 pr-6 font-semibold">
                            <ExtLink href={entry.url}>{shortUrl(entry.url, 44)}</ExtLink>
                          </td>
                          <td className="min-w-[16rem] pr-4 text-xs text-[var(--text-2)]">
                            {entry.queries.join(" · ")}
                          </td>
                          <td className="pr-4 tabular-nums text-xs text-[var(--text-2)]">
                            {entry.still_cited_on > 0 ? (
                              `${entry.still_cited_on} ${entry.still_cited_on === 1 ? "question" : "questions"}`
                            ) : (
                              <span className="bp-neg">none</span>
                            )}
                          </td>
                          <td className="py-1.5 text-right">
                            <AddToPlan
                              gapRef={`refresh:${entry.url}`}
                              title={`Refresh ${shortUrl(entry.url, 32)}`}
                              actionText={`Lost its citation on: ${entry.queries.join("; ")}. Update dates, figures and examples.`}
                              link="/dashboard/action-plan"
                            />
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
            <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">
              Pages to write
            </h2>
            {data!.strike_zone && (
              <div className="mb-4 flex flex-wrap gap-2 text-xs">
                {(["winnable now", "contested", "locked in", "needs history"] as const)
                  .filter((k) => data!.strike_zone[k])
                  .map((k) => (
                    <span
                      key={k}
                      className={`rounded-[4px] border border-[var(--border)] px-2.5 py-1 font-medium ${CONTEST_CHIP[k] ?? ""}`}
                    >
                      {data!.strike_zone[k]} {k}
                    </span>
                  ))}
              </div>
            )}
            {briefs.length === 0 && (
              <p className="card p-5 text-sm text-[var(--text-2)]">No content gaps right now.</p>
            )}
            <div className="space-y-5">
              {briefs.map((b) => (
                <article
                  key={b.query_id}
                  id={`brief-${b.query_id}`}
                  className={`scroll-mt-24 rounded-lg border p-5 ${DIAG_STYLE[b.diagnosis.type] ?? DIAG_STYLE.undetermined}`}
                >
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-base font-semibold">{b.query}</h3>
                    <span className="flex items-center gap-3 text-xs font-medium">
                      {b.contestability && (
                        <span
                          className={CONTEST_CHIP[b.contestability.label] ?? "text-[var(--text-3)]"}
                          title={
                            b.contestability.score === null
                              ? "Needs at least two runs of history to score"
                              : `How often the answer changes ${b.contestability.volatility} × reliance on web search ${b.contestability.dependence}`
                          }
                        >
                          {b.contestability.score !== null && `${b.contestability.score} · `}
                          {b.contestability.label}
                        </span>
                      )}
                      <span className={DIAG_CHIP[b.diagnosis.type] ?? ""}>
                        {b.diagnosis.label} · {b.corpus_tag}
                      </span>
                      <AddToPlan
                        gapRef={`brief:${b.query}`}
                        title={`Write: ${b.query}`}
                        actionText={b.diagnosis.fix}
                        link="/dashboard/action-plan"
                        queryText={b.query}
                      />
                    </span>
                  </div>
                  <p className="mb-4 text-sm text-[var(--text-2)]"><Linkify text={b.diagnosis.fix} /></p>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="mb-1 text-xs font-medium text-[var(--text-2)]">The gap</div>
                      <ul className="space-y-1 text-sm text-[var(--text-2)]">
                        <li className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="font-semibold text-[var(--text)]">Missing on</span>
                          {b.engines_missing.length === 0
                            ? "—"
                            : b.engines_missing.map((e) => (
                                <span key={e} className="inline-flex items-center gap-1">
                                  <EngineMark surface={e} size={16} />
                                  {e}
                                </span>
                              ))}
                        </li>
                        <li>
                          <span className="font-semibold text-[var(--text)]">Winning instead</span>{" "}
                          {b.competitors_winning.join(", ") || "no clear rival"}
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
                              <ExtLink href={`https://${s.domain}`}>{s.domain}</ExtLink>
                              <span className="ml-2 text-xs text-[var(--text-3)]">
                                cites {s.rivals.join(", ")}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div>
                      {b.spam_risk && (
                        <p className="mb-2 text-xs text-[var(--text-2)]">
                          <span className="font-semibold text-[var(--text)]">Spam-policy risk:</span>{" "}
                          {b.spam_risk.note}
                        </p>
                      )}
                      <div className="mb-1 text-xs font-medium text-[var(--text-2)]">Suggested outline</div>
                      <Bullets items={b.outline.map((line) => ({ text: line }))} className="text-xs [&_li]:text-[12.5px]" />
                    </div>
                  </div>

                  {b.subtopics.length > 0 && (
                    <div className="mt-4 border-t border-[var(--border)] pt-3">
                      <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-[var(--text-2)]">
                        Sub-searches to cover
                        <span
                          className="chip text-[10px]"
                          title={
                            b.subtopics_source === "observed"
                              ? "The sub-searches engines ran for this question"
                              : "Related questions from the same set (no fan-out seen for this question yet)"
                          }
                        >
                          {b.subtopics_source === "observed" ? "from fan-out" : "related questions"}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1.5 text-[11px]">
                        {b.subtopics.map((s, i) => (
                          <span key={i} className="chip">
                            {s}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {b.citability?.ready && (
                    <div className="mt-4 border-t border-[var(--border)] pt-3">
                      <div className="mb-1.5 text-xs font-medium text-[var(--text-2)]">
                        How the cited pages differ from yours
                      </div>
                      <div className="mb-2 flex flex-wrap gap-1.5 text-[11px]">
                        {b.citability.spec?.has_answer_capsule && (
                          <span className="chip text-[var(--pos)]">short answers under headings</span>
                        )}
                        {(b.citability.spec?.statistic_count ?? 0) >= 5 && (
                          <span className="chip text-[var(--pos)]">
                            ~{b.citability.spec!.statistic_count} data points
                          </span>
                        )}
                        {b.citability.spec?.quotations && (
                          <span className="chip text-[var(--pos)]">quotes from named sources</span>
                        )}
                        {(b.citability.spec?.citation_count ?? 0) >= 3 && (
                          <span className="chip text-[var(--pos)]">
                            ~{b.citability.spec!.citation_count} cited sources
                          </span>
                        )}
                        {b.citability.spec?.front_loaded && (
                          <span className="chip text-[var(--pos)]">answer near the top</span>
                        )}
                        <span className="chip">~{b.citability.spec?.word_count} words</span>
                        {b.citability.spec?.json_ld && <span className="chip">structured data (JSON-LD)</span>}
                        {b.citability.spec?.has_tables && <span className="chip">tables</span>}
                        {b.citability.your_page && (
                          <span className="chip">
                            <ExtLink href={b.citability.your_page.url}>your page</ExtLink>
                          </span>
                        )}
                      </div>
                      <Bullets items={(b.citability.gaps ?? []).map((gap) => ({ text: gap, tone: "bad" as const }))} className="[&_li]:text-[12.5px]" />
                    </div>
                  )}

                  <MarkShipped queryText={b.query} intervention={b.intervention ?? null} />
                </article>
              ))}
            </div>
          </section>

          {/* Proof — the fix→proof loop */}
          {(proof.data?.interventions.length ?? 0) > 0 && (
            <section className="card p-4">
              <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">
                Results of shipped fixes
              </h2>
              {proof.data!.aggregate && (
                <div className="mb-4 flex flex-wrap gap-2 text-xs">
                  <span className="chip">
                    {proof.data!.aggregate.measured} measured
                  </span>
                  <span className="chip">
                    fixed <Delta value={proof.data!.aggregate.avg_delta} unit=" pts" />
                  </span>
                  {proof.data!.aggregate.avg_control_delta !== null && (
                    <span className="chip">
                      untouched <Delta value={proof.data!.aggregate.avg_control_delta} unit=" pts" />
                    </span>
                  )}
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-[var(--text-2)]">
                    <tr>
                      <th className="py-2 pr-4">Question</th>
                      <th className="pr-4">Shipped</th>
                      <th className="pr-4">Before → after</th>
                      <th className="pr-4">Lift</th>
                      <th>Newly visible</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proof.data!.interventions.map((iv) => (
                      <tr key={iv.id} className="border-t border-[var(--border)] align-top">
                        <td className="max-w-xs py-2.5 pr-4 font-semibold">
                          {iv.query}
                          {iv.url && (
                            <span className="ml-2 text-xs font-normal">
                              <ExtLink href={iv.url}>fix</ExtLink>
                            </span>
                          )}
                        </td>
                        <td className="pr-4 text-xs tabular-nums text-[var(--text-2)]">
                          {fmtDay(iv.shipped_at)}
                        </td>
                        {iv.awaiting ? (
                          <td colSpan={3} className="text-xs text-[var(--text-3)]">
                            Measuring from the next run.
                          </td>
                        ) : (
                          <>
                            <td className="pr-4 text-xs tabular-nums">
                              {iv.before_rate ?? "—"}% → {iv.after_rate ?? "—"}%
                            </td>
                            <td className="pr-4 text-xs tabular-nums">
                              {iv.delta === null ? (
                                <span className="text-[var(--text-3)]">no baseline</span>
                              ) : (
                                <Delta value={iv.delta} unit=" pts" />
                              )}
                              {iv.delta !== null && iv.control_delta !== null && (
                                <span className="ml-1.5 text-[var(--text-3)]">
                                  untouched {iv.control_delta >= 0 ? "+" : ""}
                                  {iv.control_delta}
                                </span>
                              )}
                            </td>
                            <td className="text-xs text-[var(--text-2)]">
                              {iv.newly_visible.length ? (
                                <span className="flex gap-1">
                                  {iv.newly_visible.map((x) => (
                                    <span key={x} title={surfaceLabel(x)}>
                                      <EngineMark surface={x} size={16} />
                                    </span>
                                  ))}
                                </span>
                              ) : (
                                "—"
                              )}
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
