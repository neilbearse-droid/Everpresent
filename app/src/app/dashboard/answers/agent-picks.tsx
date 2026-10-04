import type { AgentPicks, PickSummary, RateSummary } from "@/lib/api";

function Pct({ r }: { r: RateSummary }) {
  return (
    <span className="tabular-nums">
      {Math.round(r.rate)}%
      <span className="ml-1 text-xs text-[var(--text-3)]">
        {Math.round(r.low)}–{Math.round(r.high)} · n={r.answers}
      </span>
    </span>
  );
}

function Rival({ s }: { s: PickSummary }) {
  if (!s.top_rival) return <span className="text-[var(--text-3)]">—</span>;
  const ahead = s.top_rival.rate > s.first_pick.high;
  return (
    <span className="tabular-nums">
      {ahead ? <span className="bp-neg">{s.top_rival.name}</span> : s.top_rival.name}{" "}
      {Math.round(s.top_rival.rate)}%
    </span>
  );
}

/** Task and coding prompts: whose product the AI reaches for first. */
export function AgentPicksSection({ d }: { d: AgentPicks }) {
  return (
    <section className="blueprint mb-6 grid-cols-1">
      <div>
        <div className="bp-bar">
          <span>Agent picks: who AI chooses when asked to do the job</span>
          <span>{d.days ? `last ${d.days} days` : ""}</span>
        </div>
        {!d.has_prompts ? (
          <p className="p-4 text-sm text-[var(--text-2)]">
            No task or coding prompts yet. Add queries with <code>corpus: agent_task</code> (&ldquo;register
            a domain for my bakery&rdquo;) or <code>corpus: agent_code</code> (&ldquo;write a script that
            registers a domain&rdquo;) to the config to measure which brand gets picked first.
          </p>
        ) : !d.has_data || !d.overall ? (
          <p className="p-4 text-sm text-[var(--text-2)]">
            Task and coding prompts are set up. The first picks appear after the next run.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-px md:grid-cols-3">
              <div className="p-4">
                <div className="bp-label">Picked first</div>
                <div className="bp-metric mt-1 text-[28px]">{Math.round(d.overall.first_pick.rate)}%</div>
                <div className="text-[11px] text-[var(--text-3)]">
                  {Math.round(d.overall.first_pick.low)}–{Math.round(d.overall.first_pick.high)}% range ·{" "}
                  {d.overall.first_pick.answers} answers
                </div>
              </div>
              <div className="p-4">
                <div className="bp-label">Named at all</div>
                <div className="bp-metric mt-1 text-[28px]">{Math.round(d.overall.named.rate)}%</div>
                <div className="text-[11px] text-[var(--text-3)]">named but not chosen is a near miss</div>
              </div>
              <div className="p-4">
                <div className="bp-label">Rival picked most</div>
                <div className="mt-1 text-[18px] font-semibold"><Rival s={d.overall} /></div>
                <div className="text-[11px] text-[var(--text-3)]">{d.overall.no_pick}% of answers picked no tracked brand</div>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="bp-table w-full min-w-[560px]">
                <thead>
                  <tr>
                    <th>Engine</th>
                    <th>{d.brand} picked first</th>
                    <th>Named</th>
                    <th>Top rival pick</th>
                  </tr>
                </thead>
                <tbody>
                  {[...d.kinds.map((k) => ({ key: `k-${k.kind}`, label: `All ${k.kind.toLowerCase()} prompts`, s: k })),
                    ...d.engines.map((e) => ({ key: e.surface, label: e.label, s: e }))].map((row) => (
                    <tr key={row.key}>
                      <td>{row.label}</td>
                      <td><Pct r={row.s.first_pick} /></td>
                      <td className="tabular-nums">{Math.round(row.s.named.rate)}%</td>
                      <td><Rival s={row.s} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="bp-bar">
              <span>By prompt, weakest first</span>
              <span>Picked first · who wins</span>
            </div>
            <ul>
              {d.prompts.map((p) => (
                <li key={p.text} className="border-t border-[var(--line)] px-4 py-2.5 first:border-t-0">
                  <div className="flex items-baseline justify-between gap-4 text-[13px]">
                    <span>
                      <span className="mr-2 text-xs text-[var(--text-3)]">{p.kind}</span>
                      {p.text}
                    </span>
                    <span className="shrink-0 tabular-nums">
                      {Math.round(p.first_pick.rate)}% · {p.leader ?? "no pick"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            <p className="px-4 pb-3 pt-2 text-xs text-[var(--text-3)]">
              The pick is the first tracked brand an answer names. Coding agents choose a vendor by its
              docs and SDK: clear API docs, copyable examples and an llms.txt help here.
            </p>
          </>
        )}
      </div>
    </section>
  );
}
