import { apiFetch, type AgentPicks, type AnswerShape, type Me, type RateSummary } from "@/lib/api";
import { AgentPicksSection } from "./agent-picks";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { EngineMark } from "@/components/ui";
import { AddToPlan } from "@/components/plan-buttons";

const VERDICT_HELP: Record<string, string> = {
  "known, but losing in search": "The model names you from memory, but when it searches the web it finds others. Work on the pages it finds: your own and the third-party pages it cites.",
  "found by search, not yet known": "Searching the web finds you, but the model doesn't name you from memory. Third-party coverage that stays up can be picked up when models are retrained.",
  consistent: "Memory and search agree within the noise.",
  "needs data": "Not enough answers yet on one side.",
};

function pct(n: number) {
  return `${Math.round(n)}%`;
}

function Rate({ r }: { r: RateSummary | null }) {
  if (!r) return <span className="text-[var(--text-3)]">—</span>;
  return (
    <span className="tabular-nums">
      {pct(r.rate)}
      <span className="ml-1 text-xs text-[var(--text-3)]">
        {Math.round(r.low)}–{Math.round(r.high)} · n={r.answers}
      </span>
    </span>
  );
}

export default async function AnswerShapePage() {
  const [me, res, picks] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<AnswerShape>("/api/tenant/answer-shape?days=60"),
    apiFetch<AgentPicks>("/api/tenant/agent-picks"),
  ]);
  if (res.status === 403) {
    return <NoOrgNotice active="How engines answer" isSuperadmin={me.data?.is_superadmin} detail={res.error} />;
  }
  const d = res.data;

  // The lead: whether the engines know you from memory or only find you by
  // searching, and what that means for where the work goes.
  const mvs = d && d.has_data ? d.memory_vs_search : [];
  const losing = mvs.filter((m) => m.verdict === "known, but losing in search");
  const unknown = mvs.filter((m) => m.verdict === "found by search, not yet known");
  const consistent = mvs.filter((m) => m.verdict === "consistent");
  const switches = d && d.has_data ? d.model_changes.length : 0;
  const objection = d && d.has_data ? [...d.perception.themes].sort((a, b) => b.objections - a.objections)[0] : null;
  const unlinked = d && d.has_data ? [...d.engines].filter((e) => e.answers >= 5).sort((a, b) => b.mentioned_unlinked_share - a.mentioned_unlinked_share)[0] : null;
  const lead =
    !d || !d.has_data
      ? {
          tells: "No answers yet; this fills in after the next run.",
          act: "Nothing to do yet.",
          tone: "neutral" as const,
        }
      : {
          tells:
            losing.length > 0 ? (
              <>
                {losing.map((m) => m.label).join(" and ")} {losing.length === 1 ? "knows" : "know"} you
                from memory but {losing.length === 1 ? "picks" : "pick"} rivals when searching.
              </>
            ) : unknown.length > 0 ? (
              <>
                {unknown.map((m) => m.label).join(" and ")} {unknown.length === 1 ? "finds" : "find"} you
                only by searching the web.
              </>
            ) : objection && objection.objections > 0 ? (
              <>
                Memory and search agree; the main objection is {objection.theme} ({objection.objections}).
              </>
            ) : (
              <>Memory and search agree on {consistent.length === mvs.length ? "every engine" : `${consistent.length} of ${mvs.length} engines`}.</>
            ),
          act:
            losing.length > 0
              ? "Fix the pages engines find when they search."
              : objection && objection.objections > 0
                ? `Answer the ${objection.theme} objection on your own site.`
                : unknown.length > 0
                  ? "Keep third-party coverage current."
                  : unlinked && unlinked.mentioned_unlinked_share >= 25
                    ? `Make your answer pages linkable; ${unlinked.label} names you without linking.`
                    : "Nothing to change.",
          href: losing.length > 0 || (objection && objection.objections > 0) ? "/dashboard/pages" : unlinked && unlinked.mentioned_unlinked_share >= 25 ? "/dashboard/citations" : undefined,
          hrefLabel: losing.length > 0 || (objection && objection.objections > 0) ? "Your Pages" : "Citations",
          tone: (losing.length > consistent.length ? "bad" : losing.length === 0 && unknown.length === 0 && mvs.length > 0 ? "good" : "neutral") as "good" | "bad" | "neutral",
        };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="How engines answer" isSuperadmin={me.data?.is_superadmin} />
      <PageLead {...lead} />

      {!d ? (
        <p className="text-sm text-[var(--text-2)]">{res.error}</p>
      ) : !d.has_data ? (
        <section className="card p-5 text-sm text-[var(--text-2)]">
          No answers in the last {d.days} days yet. This fills in after the next run.
        </section>
      ) : (
        <>
          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-2">
            <div>
              <div className="bp-bar">
                <span>Do they know you, or only find you?</span>
                <span>Names you · 95% range</span>
              </div>
              <div className="overflow-x-auto">
                <table className="bp-table w-full min-w-[520px]">
                  <thead>
                    <tr>
                      <th>Engine</th>
                      <th>From memory</th>
                      <th>With search</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.memory_vs_search.map((m) => (
                      <tr key={m.surface}>
                        <td>
                          <div className="flex items-center gap-2 font-semibold">
                            <EngineMark surface={m.surface} size={18} />
                            {m.label}
                          </div>
                          <div className="mt-0.5 text-xs" title={VERDICT_HELP[m.verdict]}>
                            {m.verdict === "known, but losing in search" ? (
                              <span className="bp-neg">▼ losing in search</span>
                            ) : m.verdict === "found by search, not yet known" ? (
                              <span className="text-[var(--text-2)]">search only</span>
                            ) : (
                              <span className="text-[var(--text-3)]">{m.verdict}</span>
                            )}
                          </div>
                          {m.verdict === "known, but losing in search" && (
                            <div className="mt-1.5">
                              <AddToPlan
                                gapRef={`engine-search:${m.surface}`}
                                title={`Win ${m.label} web searches`}
                                actionText={`${m.label} names you from memory (${m.memory ? Math.round(m.memory.rate) : 0}%) but not when it searches (${m.search ? Math.round(m.search.rate) : 0}%). Fix the pages it finds.`}
                                link="/dashboard/pages"
                              />
                            </div>
                          )}
                        </td>
                        <td><Rate r={m.memory} /></td>
                        <td><Rate r={m.search} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <div className="bp-bar">
                <span>What engines say about you</span>
                <span>{d.perception.sentences.toLocaleString()} sentences</span>
              </div>
              {d.perception.themes.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">No themes yet.</p>
              ) : (
                <ul>
                  {d.perception.themes.map((t) => (
                    <li key={t.theme} className="border-t border-[var(--line)] px-4 py-3 first:border-t-0">
                      <div className="flex items-baseline justify-between gap-3 text-[13px]">
                        <span className="font-semibold">{t.theme}</span>
                        <span className="tabular-nums text-[var(--text-2)]">
                          <span className="font-semibold text-[var(--text)]">{t.mentions}</span> mentions
                          {t.objections > 0 && (
                            <>
                              {" · "}
                              <span className="bp-neg">▼ {t.objections} objections</span>
                            </>
                          )}
                        </span>
                      </div>
                      {t.examples.length > 0 && (
                        <p className="mt-1 text-xs italic text-[var(--text-2)]">&ldquo;{t.examples[0]}&rdquo;</p>
                      )}
                      <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-[11.5px] text-[var(--text-3)]">
                          {t.memory} from memory · {t.search} with search
                        </p>
                        {t.objections > 0 && (
                          <AddToPlan
                            gapRef={`objection:${t.theme}`}
                            title={`Answer the ${t.theme} objection`}
                            actionText={`${t.objections} of ${t.mentions} mentions of ${t.theme} are objections${t.examples[0] ? `, e.g. "${t.examples[0]}"` : ""}. Answer it on your own site.`}
                            link="/dashboard/pages"
                          />
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
          <section className="blueprint mb-6 grid-cols-1">
            <div>
              <div className="bp-bar">
                <span>Shape by engine and model</span>
                <span>Last {d.days} days · category questions</span>
              </div>
              <div className="overflow-x-auto">
                <table className="bp-table w-full min-w-[980px]">
                  <thead>
                    <tr>
                      <th>Engine</th>
                      <th>Model</th>
                      <th className="text-right">Answers</th>
                      <th className="text-right" title="Share of answers where the engine searched the web on its own">Searched</th>
                      <th className="text-right">Links</th>
                      <th className="text-right" title="Links on words in the answer, not footnotes">In-text links</th>
                      <th className="text-right">To your site</th>
                      <th className="text-right">Third-party</th>
                      <th className="text-right">Rivals</th>
                      <th className="text-right">Names you</th>
                      <th className="text-right" title="Answers that name you but don't link your site">Named, no link</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.engines.map((e) => (
                      <tr key={`${e.surface}-${e.model}`}>
                        <td className="font-semibold">
                          <span className="inline-flex items-center gap-2">
                            <EngineMark surface={e.surface} size={16} />
                            {e.label}
                          </span>
                          {e.logged_in === false && (
                            <span className="ml-2 text-xs text-[var(--text-3)]">signed out</span>
                          )}
                        </td>
                        <td className="text-[12.5px] text-[var(--text-2)]">
                          {e.model || <span className="text-[var(--text-3)]">{e.model_note}</span>}
                        </td>
                        <td className="text-right tabular-nums">{e.answers}</td>
                        <td className="text-right tabular-nums" title={e.search_rate_source}>
                          {pct(e.search_rate)}
                        </td>
                        <td className="text-right tabular-nums">{e.citations_per_answer}</td>
                        <td className="text-right tabular-nums">{pct(e.inline_share)}</td>
                        <td className="text-right tabular-nums">{pct(e.own_share)}</td>
                        <td className="text-right tabular-nums">{pct(e.third_party_share)}</td>
                        <td className="text-right tabular-nums">{pct(e.rival_share)}</td>
                        <td className="text-right font-semibold"><Rate r={e.mention} /></td>
                        <td className="text-right tabular-nums">{pct(e.mentioned_unlinked_share)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section className="blueprint mb-6 mt-8 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <div>
              <div className="bp-bar">
                <span>Current models</span>
                <span>Per engine</span>
              </div>
              <ul>
                {Object.entries(d.current_models).length === 0 ? (
                  <li className="p-4 text-sm text-[var(--text-3)]">—</li>
                ) : (
                  Object.entries(d.current_models).map(([engine, model]) => (
                    <li key={engine} className="flex justify-between border-t border-[var(--line)] px-4 py-2.5 text-[13px] first:border-t-0">
                      <span className="inline-flex items-center gap-2 font-semibold">
                        <EngineMark surface={engine} size={16} />
                        {engine}
                      </span>
                      <span className="tabular-nums text-[var(--text-2)]">{model}</span>
                    </li>
                  ))
                )}
              </ul>
            </div>
            <div>
              <div className="bp-bar">
                <span>Model changes</span>
                <span>Last {d.days} days</span>
              </div>
              {d.model_changes.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">None in {d.days} days.</p>
              ) : (
                <ul>
                  {d.model_changes.map((c) => (
                    <li key={`${c.surface}-${c.model}-${c.since}`} className="border-t border-[var(--line)] px-4 py-2.5 text-[13px] first:border-t-0">
                      <span className="tabular-nums text-[var(--text-3)]">{c.since}</span>{" "}
                      <span className="inline-flex items-center gap-1.5 align-middle font-semibold">
                        <EngineMark surface={c.surface} size={16} />
                        {c.label}
                      </span>{" "}
                      <span className="text-[var(--text-2)]">→</span> <span className="bp-mark">{c.model}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

        </>
      )}
      {picks.data && <AgentPicksSection d={picks.data} />}
    </main>
  );
}
