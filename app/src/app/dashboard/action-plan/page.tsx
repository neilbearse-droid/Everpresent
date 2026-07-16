import { apiFetch, type ActionPlan, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { surfaceLabel } from "@/lib/viz";

const DIAG_STYLE: Record<string, string> = {
  content_gap: "border-amber-500/40 bg-amber-500/5",
  knowledge_gap: "border-red-500/40 bg-red-500/5",
  undetermined: "border-[var(--border)] bg-slate-900",
};
const DIAG_CHIP: Record<string, string> = {
  content_gap: "text-amber-300",
  knowledge_gap: "text-red-300",
  undetermined: "text-slate-400",
};

export default async function ActionPlanPage() {
  const [me, plan] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<ActionPlan>("/api/tenant/action-plan"),
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
          <p className="text-sm text-slate-400">
            Once a run finds visibility gaps, this tab turns each one into a source target
            list and a ready-to-work content brief.
          </p>
        </section>
      ) : (
        <div className="space-y-8">
          {/* #4 — Citation-gap target list */}
          <section className="card p-6">
            <h2 className="mb-1 text-sm font-medium text-slate-400">
              Source targets — where the AIs get their answers in your vertical
            </h2>
            <p className="mb-4 text-xs text-slate-500">
              Third-party domains that AI answers cite alongside your competitors — but not
              you. Getting {data!.brand_name} covered on these is the highest-leverage way to
              enter the answers. Rivals' own sites and your own domains are excluded.
            </p>
            {targets.length === 0 ? (
              <p className="text-sm text-slate-500">No third-party source gaps found.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-slate-400">
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
                            className="font-mono text-indigo-400 hover:underline"
                          >
                            {t.domain}
                          </a>
                        </td>
                        <td className="pr-4 tabular-nums">{t.competitor_assoc}×</td>
                        <td className="pr-4 tabular-nums">{t.queries}</td>
                        <td className="pr-4 text-xs text-slate-400">
                          {t.surfaces.map(surfaceLabel).join(", ")}
                        </td>
                        <td>
                          {t.already_citing_you ? (
                            <span className="text-emerald-400">already cites you</span>
                          ) : (
                            <span className="text-amber-300">target</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* #1 — Content briefs */}
          <section>
            <h2 className="mb-1 text-sm font-medium text-slate-400">
              Content briefs — one per gap, ready to hand to a writer
            </h2>
            <p className="mb-4 text-xs text-slate-500">
              Each gap query, turned into a brief: what to write, who's beating you, which
              sources to earn, and the questions to cover so AI answer engines can cite it.
            </p>
            <div className="space-y-5">
              {briefs.map((b) => (
                <article
                  key={b.query_id}
                  className={`rounded-lg border p-5 ${DIAG_STYLE[b.diagnosis.type] ?? DIAG_STYLE.undetermined}`}
                >
                  <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-base font-medium">{b.query}</h3>
                    <span className={`text-xs font-medium ${DIAG_CHIP[b.diagnosis.type] ?? ""}`}>
                      {b.diagnosis.label} · {b.corpus_tag}
                    </span>
                  </div>
                  <p className="mb-4 text-sm text-slate-300">{b.diagnosis.fix}</p>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="mb-1 text-xs font-medium text-slate-400">Why it matters</div>
                      <ul className="space-y-1 text-sm text-slate-300">
                        <li>
                          Missing on:{" "}
                          <span className="text-amber-300">
                            {b.engines_missing.join(", ") || "—"}
                          </span>
                        </li>
                        <li>
                          Winning instead:{" "}
                          <span className="text-slate-200">
                            {b.competitors_winning.join(", ") || "no clear rival"}
                          </span>
                        </li>
                      </ul>
                      <div className="m-1 mt-3 mb-1 text-xs font-medium text-slate-400">
                        Earn a citation on
                      </div>
                      {b.target_sources.length === 0 ? (
                        <p className="text-sm text-slate-500">No specific source yet.</p>
                      ) : (
                        <ul className="space-y-1 text-sm">
                          {b.target_sources.map((s) => (
                            <li key={s.domain}>
                              <span className="font-mono text-indigo-300">{s.domain}</span>
                              <span className="ml-2 text-xs text-slate-500">
                                cites {s.rivals.join(", ")}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div>
                      <div className="mb-1 text-xs font-medium text-slate-400">Suggested outline</div>
                      <ul className="space-y-1 text-sm text-slate-300">
                        {b.outline.map((line, i) => (
                          <li key={i} className="text-xs">
                            {line}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
