import { apiFetch, type AgentPicks, type AnswerShape, type Me, type RateSummary } from "@/lib/api";
import { AgentPicksSection } from "./agent-picks";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";

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
          tells: `No answers in the last ${d?.days ?? 60} days. After the next run this page shows which engines know you from memory, which only find you by searching, and what each one says about you.`,
          act: "Nothing to do here until the next run.",
          tone: "neutral" as const,
        }
      : {
          tells: (
            <>
              {losing.length > 0 && (
                <>
                  {losing.map((m) => m.label).join(" and ")} {losing.length === 1 ? "knows" : "know"} you
                  from memory but {losing.length === 1 ? "finds" : "find"} others when{" "}
                  {losing.length === 1 ? "it searches" : "they search"}.{" "}
                </>
              )}
              {unknown.length > 0 && (
                <>
                  {unknown.map((m) => m.label).join(" and ")} {unknown.length === 1 ? "finds" : "find"} you
                  by searching but {unknown.length === 1 ? "doesn't" : "don't"} name you from memory.{" "}
                </>
              )}
              {losing.length === 0 && unknown.length === 0 && consistent.length > 0 && (
                <>Memory and search agree on {consistent.length === mvs.length ? "every engine" : `${consistent.length} of ${mvs.length} engines`}. </>
              )}
              {objection && objection.objections > 0 && (
                <>
                  The most common objection is about {objection.theme} ({objection.objections}{" "}
                  {objection.objections === 1 ? "mention" : "mentions"}).{" "}
                </>
              )}
              {switches > 0 && (
                <>
                  {switches} model {switches === 1 ? "switch" : "switches"} in the last {d.days} days
                  {switches === 1 ? " changes" : " change"} how to read the trend.
                </>
              )}
            </>
          ),
          act:
            losing.length > 0
              ? "Work on what the engines find when they search: your own pages and the third-party pages they cite for these questions. Memory is already on your side."
              : objection && objection.objections > 0
                ? `Answer the ${objection.theme} objection plainly on your own site, on the page an engine would cite for it. Engines repeat what they can quote.`
                : unknown.length > 0 && losing.length === 0
                  ? "Keep the third-party coverage that search finds up to date. Models pick it up when they're retrained; there's nothing to change on-site for this."
                  : unlinked && unlinked.mentioned_unlinked_share >= 25
                    ? `${unlinked.label} names you without linking you in ${Math.round(unlinked.mentioned_unlinked_share)}% of answers. Make the page that answers each question the obvious one to link: specific, dated, with the answer at the top.`
                    : "Nothing to change on the strength of this page. Use it to read the model switches before you read a trend.",
          href: losing.length > 0 ? "/dashboard/pages" : objection && objection.objections > 0 ? "/dashboard/pages" : "/dashboard/citations",
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
                          <div className="font-medium">{m.label}</div>
                          <div className="text-xs text-[var(--text-3)]" title={VERDICT_HELP[m.verdict]}>
                            {m.verdict}
                          </div>
                        </td>
                        <td><Rate r={m.memory} /></td>
                        <td><Rate r={m.search} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="px-4 pb-3 pt-2 text-xs text-[var(--text-3)]">
                From memory means answers given without searching the web, so they reflect what
                the model learned in training. The less often an engine searches, the more these
                answers count.
              </p>
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
                          {t.mentions} mentions ·{" "}
                          {t.objections > 0 ? (
                            <span className="bp-neg">{t.objections} objections</span>
                          ) : (
                            "no objections"
                          )}
                        </span>
                      </div>
                      {t.examples.length > 0 && (
                        <p className="mt-1 text-xs italic text-[var(--text-2)]">&ldquo;{t.examples[0]}&rdquo;</p>
                      )}
                      <p className="mt-0.5 text-[11.5px] text-[var(--text-3)]">
                        {t.memory} from memory · {t.search} with search
                      </p>
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
                      <th className="text-right">Links per answer</th>
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
                        <td className="font-medium">
                          {e.label}
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
                        <td className="text-right"><Rate r={e.mention} /></td>
                        <td className="text-right tabular-nums">{pct(e.mentioned_unlinked_share)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="px-4 pb-3 pt-2 text-xs text-[var(--text-3)]">
                For ChatGPT and Perplexity&apos;s APIs, &ldquo;Searched&rdquo; comes from a separate
                check where the engine decides for itself whether to search (the main measurement
                always searches). Answers collected from the engines&apos; websites are signed out,
                with no saved chat history. A name with no link still counts as visibility.
              </p>
            </div>
          </section>

          <p className="mb-3 mt-8 max-w-3xl text-[12.5px] leading-relaxed text-[var(--text-3)]">
            Each new model changes how an engine answers: how often it searches the web, how many
            sources it links, whether links sit in the text or in footnotes, and whether they
            point to your site or someone else&apos;s. A drop in citations can be a model switch,
            so read the numbers above per model, with the date each model started.
          </p>
          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <div>
              <div className="bp-bar">
                <span>Models answering now</span>
                <span>As reported by each API</span>
              </div>
              <ul>
                {Object.entries(d.current_models).length === 0 ? (
                  <li className="p-4 text-sm text-[var(--text-3)]">
                    Model names appear once API engines have answered.
                  </li>
                ) : (
                  Object.entries(d.current_models).map(([engine, model]) => (
                    <li key={engine} className="flex justify-between border-t border-[var(--line)] px-4 py-2.5 text-[13px] first:border-t-0">
                      <span className="font-medium">{engine}</span>
                      <span className="tabular-nums text-[var(--text-2)]">{model}</span>
                    </li>
                  ))
                )}
              </ul>
            </div>
            <div>
              <div className="bp-bar">
                <span>Model changes</span>
                <span>Read before and after separately</span>
              </div>
              {d.model_changes.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">
                  No model switches seen in the last {d.days} days.
                </p>
              ) : (
                <ul>
                  {d.model_changes.map((c) => (
                    <li key={`${c.surface}-${c.model}-${c.since}`} className="border-t border-[var(--line)] px-4 py-2.5 text-[13px] first:border-t-0">
                      <span className="tabular-nums text-[var(--text-3)]">{c.since}</span>{" "}
                      <span className="font-medium">{c.label}</span> started answering with{" "}
                      <span className="bp-mark">{c.model}</span>
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
