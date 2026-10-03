import { apiFetch, type AgentAnalytics, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { UploadLogs } from "./upload-form";

const PURPOSE_LABEL: Record<string, string> = {
  search: "Indexing for answers",
  user: "Live fetch for a user",
  agent: "AI agent browsing",
  training: "Model training",
};

const PURPOSE_HELP: Record<string, string> = {
  search: "Crawling so the engine can cite you later. This is what earns visibility.",
  user: "Someone asked an AI about this page right now. The closest signal of real demand.",
  agent: "An AI browser acting for a person (shopping, booking, comparing).",
  training: "Collecting text for future models. No direct visibility payoff.",
};

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="p-3">
      <div className="bp-label">{label}</div>
      <div className="bp-metric mt-1 text-[24px]">{value}</div>
      {sub && <div className="text-[11px] text-[var(--text-3)]">{sub}</div>}
    </div>
  );
}

export default async function AgentsPage() {
  const [me, res] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<AgentAnalytics>("/api/tenant/agent-analytics?days=30"),
  ]);
  if (res.status === 403) {
    return <NoOrgNotice active="AI Agents" isSuperadmin={me.data?.is_superadmin} detail={res.error} />;
  }
  const d = res.data;

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="AI Agents" isSuperadmin={me.data?.is_superadmin} />

      <section className="blueprint mb-6 grid-cols-1 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="p-5">
          <div className="bp-label mb-2">AI Agents / who reads your site</div>
          <h1 className="text-2xl font-semibold tracking-tight">Which AI bots read your pages</h1>
          <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-[var(--text-2)]">
            From your server or CDN logs: every AI crawler and agent that fetched your pages,
            why it came, and whether those pages then get cited in AI answers.
          </p>
        </div>
        <div className="p-5">
          <UploadLogs />
        </div>
      </section>

      {!d ? (
        <p className="text-sm text-[var(--text-2)]">{res.error}</p>
      ) : !d.has_data ? (
        <section className="card p-5 text-sm text-[var(--text-2)]">
          No AI-bot traffic yet for the last {d.days} days. Upload an access log above, or ask
          your EverPresent admin for a log-push token to stream logs in automatically.
        </section>
      ) : (
        <>
          <section className="blueprint mb-6 grid-cols-2 md:grid-cols-4">
            <Stat label="AI-bot requests (30d)" value={d.total_hits.toLocaleString()} />
            <Stat
              label="Live user fetches"
              value={d.by_purpose.user.toLocaleString()}
              sub="someone asked an AI about your page"
            />
            <Stat
              label="Verified by IP"
              value={`${d.verified_share}%`}
              sub="the rest only claimed the bot name"
            />
            <Stat
              label="Errors served to bots"
              value={`${d.error_rate}%`}
              sub="4xx/5xx responses"
            />
          </section>

          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-2">
            <div>
              <div className="bp-bar">
                <span>Why they came</span>
                <span>Requests</span>
              </div>
              <ul>
                {(["search", "user", "agent", "training"] as const).map((k) => (
                  <li key={k} className="border-t border-[var(--line)] px-4 py-2.5 first:border-t-0">
                    <div className="flex justify-between text-[13px] font-semibold">
                      <span>{PURPOSE_LABEL[k]}</span>
                      <span className="tabular-nums">{d.by_purpose[k].toLocaleString()}</span>
                    </div>
                    <p className="text-xs text-[var(--text-3)]">{PURPOSE_HELP[k]}</p>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="bp-bar">
                <span>By bot</span>
                <span>Requests · verified · errors</span>
              </div>
              <div className="overflow-x-auto"><table className="bp-table w-full min-w-[460px]">
                <tbody>
                  {d.by_bot.slice(0, 12).map((b) => (
                    <tr key={b.bot}>
                      <td>
                        {b.bot}
                        <span className="ml-2 text-xs text-[var(--text-3)]">
                          {b.company} · {PURPOSE_LABEL[b.purpose] ?? b.purpose}
                        </span>
                      </td>
                      <td className="tabular-nums">{b.hits.toLocaleString()}</td>
                      <td className="tabular-nums text-[var(--text-2)]">
                        {b.hits ? Math.round((100 * b.verified) / b.hits) : 0}%
                      </td>
                      <td className="tabular-nums text-[var(--text-2)]">{b.errors}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </div>
          </section>

          <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-2">
            <div>
              <div className="bp-bar">
                <span>Read by AI, never cited</span>
                <span>Fix these first</span>
              </div>
              {d.read_not_cited.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">
                  Every page AI engines read is also being cited. Nothing to fix here.
                </p>
              ) : (
                <div className="overflow-x-auto"><table className="bp-table w-full min-w-[460px]">
                  <tbody>
                    {d.read_not_cited.map((p) => (
                      <tr key={p.path}>
                        <td className="break-all">{p.path}</td>
                        <td className="tabular-nums">{(p.search + p.user).toLocaleString()} reads</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )}
              <p className="px-4 pb-3 text-xs text-[var(--text-3)]">
                Answer engines are considering these pages and choosing other sources. Lead with a
                direct answer, add current facts and dates, and check they render without JavaScript.
              </p>
            </div>
            <div>
              <div className="bp-bar">
                <span>Cited, but at risk</span>
                <span>{d.cited_at_risk.length}</span>
              </div>
              {d.cited_at_risk.length === 0 ? (
                <p className="p-4 text-sm text-[var(--text-2)]">
                  No cited page is erroring for AI bots or going unread.
                </p>
              ) : (
                <div className="overflow-x-auto"><table className="bp-table w-full min-w-[460px]">
                  <tbody>
                    {d.cited_at_risk.map((p) => (
                      <tr key={p.path}>
                        <td className="break-all">{p.path}</td>
                        <td className="text-[var(--text-2)]">{p.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )}
              {(d.broken_pages ?? []).length > 0 && (
                <>
                  <div className="bp-bar">
                    <span>Broken for AI bots</span>
                    <span className="bp-neg">{d.broken_pages.length}</span>
                  </div>
                  <div className="overflow-x-auto"><table className="bp-table w-full min-w-[460px]">
                    <tbody>
                      {d.broken_pages.map((p) => (
                        <tr key={p.path}>
                          <td className="break-all">{p.path}</td>
                          <td className="tabular-nums">{p.errors.toLocaleString()} errors</td>
                        </tr>
                      ))}
                    </tbody>
                  </table></div>
                  <p className="px-4 pb-3 text-xs text-[var(--text-3)]">
                    Bots keep requesting these and getting errors. Redirect them to the live page.
                  </p>
                </>
              )}
            </div>
          </section>

          <section className="blueprint grid-cols-1">
            <div>
              <div className="bp-bar">
                <span>Most-read pages</span>
                <span>{d.pages_tracked.toLocaleString()} pages tracked</span>
              </div>
              <div className="overflow-x-auto"><table className="bp-table w-full min-w-[460px]">
                <thead>
                  <tr>
                    <th>Page</th>
                    <th>All</th>
                    <th>Indexing</th>
                    <th>Live fetch</th>
                    <th>Training</th>
                    <th>Errors</th>
                    <th>Cited</th>
                  </tr>
                </thead>
                <tbody>
                  {d.top_pages.map((p) => (
                    <tr key={p.path}>
                      <td className="break-all">{p.path}</td>
                      <td className="tabular-nums">{p.hits}</td>
                      <td className="tabular-nums">{p.search}</td>
                      <td className="tabular-nums">{p.user}</td>
                      <td className="tabular-nums">{p.training}</td>
                      <td className="tabular-nums">{p.errors}</td>
                      <td className="tabular-nums">{p.cited || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
