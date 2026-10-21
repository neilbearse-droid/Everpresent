import Link from "next/link";
import {
  apiFetch,
  type FirstPartySummary,
  type Me,
  type OwnPages,
  type SiteSearches,
} from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { ImportFirstParty } from "./import-form";
import { fmtDate } from "@/lib/viz";

const BAD_FLAGS = new Set(["facts conflict", "unreachable", "errors for AI bots"]);
const FP_LABEL: Record<string, string> = {
  "gsc:impressions": "Google AI impressions",
  "gsc:clicks": "Google AI clicks",
  "bing:clicks": "Bing AI clicks",
  "bing:citations": "Bing/Copilot citations",
  "cloudflare:requests": "Cloudflare AI requests",
  "ga4:sessions": "AI referral sessions",
};

function fpText(fp: Record<string, number>) {
  const entries = Object.entries(fp);
  if (!entries.length) return "—";
  return entries
    .slice(0, 3)
    .map(([k, v]) => `${FP_LABEL[k] ?? k.replace(":", " ")}: ${Math.round(v).toLocaleString()}`)
    .join(" · ");
}

/** Which sites the engines searched inside while answering: yours vs rivals'. */
function SiteSearchesPanel({ s }: { s: SiteSearches }) {
  const top = s.targets[0]?.count || 1;
  return (
    <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-2">
      <div>
        <div className="bp-bar">
          <span>Sites the engines search inside</span>
          <span>last {s.days} days</span>
        </div>
        <div className="p-4">
          {s.site_searches === 0 ? (
            <p className="text-sm text-[var(--text-2)]">
              No site searches yet. Engines sometimes search inside one website to check a fact
              (a <code>site:</code> search); they show here as runs record them.
            </p>
          ) : (
            <>
              <p className="text-sm text-[var(--text-2)]">
                While answering your questions, engines searched inside{" "}
                <b className="text-[var(--text)]">your site {s.owned}</b>{" "}
                {s.owned === 1 ? "time" : "times"} and{" "}
                <b className="text-[var(--text)]">rivals&apos; sites {s.rivals}</b>{" "}
                {s.rivals === 1 ? "time" : "times"}. When an engine checks a site, that
                site&apos;s wording can end up in the answer.
              </p>
              <ul className="mt-4 space-y-2">
                {s.targets.map((t) => (
                  <li key={`${t.kind}:${t.name}`} className="text-sm">
                    <div className="flex items-center gap-3">
                      <span
                        className={`w-36 shrink-0 truncate ${t.kind === "owned" ? "font-semibold" : ""}`}
                        title={t.domains.join(", ")}
                      >
                        {t.kind === "owned" ? `${t.name} (you)` : t.name}
                      </span>
                      <span className="h-2 flex-1 rounded-r bg-[var(--surface-2)]">
                        <span
                          className="block h-2 rounded-r"
                          style={{
                            width: `${Math.max(3, (100 * t.count) / top)}%`,
                            background:
                              t.kind === "owned"
                                ? "var(--accent)"
                                : t.kind === "competitor"
                                  ? "var(--border-strong)"
                                  : "var(--border)",
                          }}
                        />
                      </span>
                      <span className="w-10 text-right tabular-nums">{t.count}</span>
                    </div>
                    {t.kind === "competitor" && t.top_asks.length > 0 && (
                      <p className="ml-[9.75rem] mt-0.5 text-xs text-[var(--text-3)]">
                        Looked for: {t.top_asks.map((a) => `“${a}”`).join(", ")}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              {!s.has_domains && (
                <p className="mt-3 text-xs text-[var(--text-3)]">
                  Add your domains in the config so searches inside your site are counted.
                </p>
              )}
            </>
          )}
        </div>
      </div>
      <div>
        <div className="bp-bar">
          <span>What they looked for on your site</span>
          <span>make sure a page answers each</span>
        </div>
        {s.looked_for.length === 0 ? (
          <p className="p-4 text-sm text-[var(--text-2)]">
            {s.owned === 0
              ? "No searches inside your site yet."
              : "The searches inside your site didn't say what they looked for."}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {s.looked_for.map((l) => (
              <li key={l.text} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                <span>“{l.text}”</span>
                <span className="shrink-0 text-xs text-[var(--text-3)]">
                  {l.count}× · {l.engines.join(", ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export default async function YourPagesPage() {
  const [me, res, fp, ss] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<OwnPages>("/api/tenant/own-pages?days=30"),
    apiFetch<FirstPartySummary>("/api/tenant/first-party"),
    apiFetch<SiteSearches>("/api/tenant/site-searches?days=30"),
  ]);
  if (res.status === 403) {
    return <NoOrgNotice active="Your Pages" isSuperadmin={me.data?.is_superadmin} detail={res.error} />;
  }
  const d = res.data;
  const sources = fp.data?.sources ?? [];
  const nSources = new Set(sources.map((s) => s.source)).size;

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Your Pages" isSuperadmin={me.data?.is_superadmin} />
      <section className="mb-6">
        <h1 className="text-[28px] font-semibold tracking-tight">Your Pages</h1>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-2)]">
          AI engines check facts on brands&apos; own sites. In Ahrefs&apos; October 2026 study of
          ChatGPT&apos;s sub-searches, most searches limited to a single site went to brand sites, so
          a stale price or a broken help page can end up in the answer. Every page of yours that
          AI answers used is listed with whether it loads, how current it looks and whether it
          agrees with your fact sheet, next to what Google and Bing report.
        </p>
      </section>

      {!d ? (
        <p className="text-sm text-[var(--text-2)]">{res.error}</p>
      ) : (
        <>
          <section className="blueprint mb-6 grid-cols-2 md:grid-cols-4">
            {[
              ["Own pages AI uses", d.pages_total.toLocaleString(), `last ${d.days} days`],
              ["Need attention", d.flagged.toLocaleString(), "conflicts, errors, stale"],
              ["Bot logs", d.has_logs ? "Connected" : "Not yet", d.has_logs ? "AI Agents tab" : "upload on AI Agents"],
              ["First-party data", nSources ? `${nSources} source${nSources === 1 ? "" : "s"}` : "None yet", "import below"],
            ].map(([label, value, sub]) => (
              <div key={label} className="p-4">
                <div className="bp-label">{label}</div>
                <div className="bp-metric mt-1 text-[26px]">{value}</div>
                <div className="mt-1 text-xs text-[var(--text-3)]">{sub}</div>
              </div>
            ))}
          </section>

          <section className="blueprint mb-6 grid-cols-1">
            <div>
              <div className="bp-bar">
                <span>Your pages in AI answers</span>
                <span>Worst first</span>
              </div>
              {d.pages.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">
                  No answers have linked your own pages in the last {d.days} days
                  {d.domains.length ? ` (${d.domains.join(", ")})` : ""}. Check your brand domains
                  in the setup, and see Recommendations for how to get cited.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="bp-table w-full min-w-[980px]">
                    <thead>
                      <tr>
                        <th>Page</th>
                        <th className="text-right">Cited</th>
                        <th>Last check</th>
                        <th>Facts</th>
                        <th className="text-right">AI bot reads</th>
                        <th>Google / Bing</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.pages.map((p) => (
                        <tr key={p.path} className="align-top">
                          <td className="max-w-[280px]">
                            <div className="font-medium [overflow-wrap:anywhere]">
                              {/* Break lines after / and -, never mid-word. */}
                              {p.path.replace(/([/-])/g, "$1\u200b")}
                            </div>
                            <div className="text-xs text-[var(--text-3)]">{p.engines.join(", ") || "not cited lately"}</div>
                          </td>
                          <td className="text-right tabular-nums">
                            {p.cited}
                            {p.inline > 0 && <div className="text-xs text-[var(--text-3)]">{p.inline} in text</div>}
                          </td>
                          <td className="text-[12.5px]">
                            {p.crawl ? (
                              <>
                                {p.crawl.status === "ok" ? "OK" : `Error ${p.crawl.http_status ?? ""}`}
                                <div className="text-xs text-[var(--text-3)]">
                                  {fmtDate(p.crawl.checked)} ·{" "}
                                  {p.crawl.has_updated_date
                                    ? "shows an updated date"
                                    : p.crawl.latest_year
                                      ? `newest year named ${p.crawl.latest_year}`
                                      : "no date shown"}
                                </div>
                              </>
                            ) : (
                              <span className="text-[var(--text-3)]">not checked yet</span>
                            )}
                          </td>
                          <td className="max-w-[260px] text-[12.5px]">
                            {p.fact_conflicts.length === 0 ? (
                              <span className="text-[var(--text-3)]">{p.crawl ? "no conflicts" : "—"}</span>
                            ) : (
                              p.fact_conflicts.slice(0, 2).map((c, i) => (
                                <div key={i} className="mb-2 last:mb-0">
                                  <div>
                                    Page says <b>&ldquo;{c.stated}&rdquo;</b>
                                  </div>
                                  <div className="text-xs text-[var(--text-2)]">
                                    Fact sheet:{" "}
                                    {c.label ||
                                      (c.kind === "disallowed"
                                        ? `never say “${c.expected}”`
                                        : `${c.subject} is ${c.expected}`)}
                                  </div>
                                  {c.snippet && (
                                    <div className="mt-1 line-clamp-2 text-xs italic text-[var(--text-3)]">
                                      &ldquo;{c.snippet}&rdquo;
                                    </div>
                                  )}
                                </div>
                              ))
                            )}
                          </td>
                          <td className="text-right tabular-nums text-[12.5px]">
                            {d.has_logs ? p.bot_reads.toLocaleString() : "—"}
                            {p.bot_errors > 0 && (
                              <div className="text-xs text-[var(--text-3)]">{p.bot_errors} errors</div>
                            )}
                          </td>
                          <td className="max-w-[220px] text-[12px] text-[var(--text-2)]">{fpText(p.first_party)}</td>
                          <td>
                            <div className="flex flex-col gap-1">
                              {p.flags.length === 0 ? (
                                <span className="bp-mark text-xs">no issues</span>
                              ) : (
                                p.flags.map((f) =>
                                  BAD_FLAGS.has(f) ? (
                                    <span key={f} className="bp-neg text-xs">{f}</span>
                                  ) : (
                                    <span key={f} className="chip">{f}</span>
                                  ),
                                )
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="px-4 pb-3 pt-2 text-xs text-[var(--text-3)]">
                Pages are re-checked nightly. A fact conflict needs a person to confirm it: a
                pricing page, for example, may list several prices. Add facts on the Brand
                tab&apos;s fact sheet (admin) to check more.
              </p>
            </div>
          </section>

          {ss.data && <SiteSearchesPanel s={ss.data} />}

          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-2">
            <div>
              <div className="bp-bar">
                <span>First-party AI data</span>
                <span>Google · Bing · Cloudflare · GA4</span>
              </div>
              <div className="p-4">
                <ImportFirstParty sources={fp.data?.available ?? { gsc: "Google Search Console" }} />
              </div>
              {sources.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="bp-table w-full min-w-[460px]">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Metric</th>
                        <th className="text-right">Total</th>
                        <th>Dates</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sources.map((s) => (
                        <tr key={`${s.source}-${s.metric}`}>
                          <td>{s.label}</td>
                          <td>{s.metric.replaceAll("_", " ")}</td>
                          <td className="text-right tabular-nums">{s.total.toLocaleString()}</td>
                          <td className="whitespace-nowrap text-xs text-[var(--text-3)]">
                            {s.from ? `${s.from} → ${s.to}` : "no dates"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div>
              <div className="bp-bar">
                <span>In AI features, not in our samples</span>
                <span>{d.in_ai_features_not_sampled.length}</span>
              </div>
              {d.in_ai_features_not_sampled.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">
                  {d.has_first_party
                    ? "Every page Google or Bing reports in AI features is also in our samples."
                    : "Import Search Console or Bing data to see pages AI features use that our tracked questions don't reach."}
                </p>
              ) : (
                <>
                  <ul>
                    {d.in_ai_features_not_sampled.map((u) => (
                      <li key={u.path} className="border-t border-[var(--line)] px-4 py-2.5 text-[13px] first:border-t-0">
                        <div className="break-all font-medium">{u.path}</div>
                        <div className="text-xs text-[var(--text-3)]">{fpText(u.first_party)}</div>
                      </li>
                    ))}
                  </ul>
                  <p className="px-4 pb-3 pt-2 text-xs text-[var(--text-3)]">
                    These pages show up in Google or Bing AI features for questions you don&apos;t
                    track yet. Add those questions on the{" "}
                    <Link href="/dashboard/queries" className="text-[var(--accent)]">Queries</Link> tab.
                  </p>
                </>
              )}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
