import { apiFetch, rangeQuery, type Me, type OutcomePayload, type Proof } from "@/lib/api";
import { ProofSection } from "./proof";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { EngineMark } from "@/components/ui";

export default async function OutcomePage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, out, proof] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<OutcomePayload>(`/api/tenant/outcome${rangeQuery(from, to)}`),
    apiFetch<Proof>("/api/tenant/proof"),
  ]);
  if (out.status === 403) {
    return <NoOrgNotice active="Visits from AI" isSuperadmin={me.data?.is_superadmin} detail={out.error} />;
  }
  const d = out.data;

  const notReady = (tells: string, act: string) => (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Visits from AI" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead tells={tells} act={act} />
      {proof.data && <ProofSection p={proof.data} />}
    </main>
  );

  if (!d || !d.connected) {
    return notReady(
      "Waiting for Google Analytics.",
      "Ask your EverPresent contact to connect your GA4 property.",
    );
  }
  if (!d.has_data) {
    return notReady("GA4 is connected; the first pull runs tonight.", "Come back tomorrow.");
  }

  const maxSessions = Math.max(...d.series.map((s) => s.sessions), 1);
  const gaps = d.tracking_gaps ?? [];

  // The lead: how many visits AI sent, from where, and which way it's going
  // (second half of the window against the first).
  const byEngine = [...d.engine_totals].sort((a, b) => b.sessions - a.sessions);
  const topEngine = byEngine[0] ?? null;
  const half = Math.floor(d.series.length / 2);
  const firstHalf = d.series.slice(0, half).reduce((n, s) => n + s.sessions, 0);
  const secondHalf = d.series.slice(half).reduce((n, s) => n + s.sessions, 0);
  const direction =
    d.series.length < 4 || firstHalf === 0
      ? null
      : secondHalf > firstHalf * 1.1
        ? "rising"
        : secondHalf < firstHalf * 0.9
          ? "falling"
          : "flat";
  const lead = {
    tells: `AI engines sent ${d.totals.sessions.toLocaleString()} ${d.totals.sessions === 1 ? "visit" : "visits"}${
      topEngine ? `, mostly from ${topEngine.engine}` : ""
    }${direction ? `, ${direction}` : ""}.`,
    act: d.totals.sessions === 0 ? "Check that engines naming you also link you." : "Ship a fix and mark its recommendation done.",
    href: d.totals.sessions === 0 ? "/dashboard/engines" : "/dashboard/action-plan",
    hrefLabel: d.totals.sessions === 0 ? "Engines" : "Action Plan",
    tone: (direction === "rising" ? "good" : direction === "falling" ? "bad" : "neutral") as "good" | "bad" | "neutral",
  };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Visits from AI" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />
      {proof.data && <ProofSection p={proof.data} />}

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="card p-4">
          <div className="text-3xl font-semibold tabular-nums">{d.totals.sessions.toLocaleString()}</div>
          <div className="mt-1 text-sm text-[var(--text-2)]">AI-referred sessions</div>
        </div>
        <div className="card p-4">
          <div className="text-3xl font-semibold tabular-nums">{d.totals.conversions.toLocaleString()}</div>
          <div className="mt-1 text-sm text-[var(--text-2)]">Key events</div>
        </div>
        <div className="card p-4">
          <div className="text-3xl font-semibold tabular-nums">{d.engine_totals.length}</div>
          <div className="mt-1 text-sm text-[var(--text-2)]">Engines sending traffic</div>
        </div>
      </div>

      <section className="mb-6 card p-4">
        <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">By engine</h2>
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-[var(--text-3)]">
            <tr>
              <th className="py-1.5 pr-4 font-medium">Engine</th>
              <th className="pr-4 font-medium">Sessions</th>
              <th className="w-1/2 pr-4"></th>
              <th className="font-medium">Key events</th>
            </tr>
          </thead>
          <tbody>
            {byEngine.map((e) => {
              const maxE = Math.max(...byEngine.map((x) => x.sessions), 1);
              return (
                <tr key={e.engine} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-4">
                    <span className="inline-flex items-center gap-2 font-semibold">
                      <EngineMark surface={e.engine} size={18} />
                      {e.engine}
                    </span>
                  </td>
                  <td className="pr-4 tabular-nums">{e.sessions.toLocaleString()}</td>
                  <td className="pr-4">
                    <div className="h-2 w-full rounded-sm bg-[var(--plane-2)]">
                      <div
                        className="h-2 rounded-sm bg-[var(--accent)]"
                        style={{ width: `${(e.sessions / maxE) * 100}%` }}
                      />
                    </div>
                  </td>
                  <td className="tabular-nums text-[var(--text-2)]">{e.conversions.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="card p-4">
        <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
          Daily sessions · visibility score above each bar
        </h2>
        {gaps.map((g) => (
          <p key={g.start} className="mb-3 text-xs text-[var(--text-3)]">
            <span className="font-semibold text-[var(--text-2)]">{g.label}:</span> {g.engine} undercounted
            (grey bars).
          </p>
        ))}
        <div className="flex gap-1" style={{ height: 140 }}>
          {d.series.map((s) => (
            <div key={s.date} className="flex h-full flex-1 flex-col items-center gap-1">
              {s.brand_score !== null && (
                <span className="text-[9px] text-[var(--pos)]">{s.brand_score}</span>
              )}
              {/* The bar's % height needs a definite-height parent. */}
              <div className="flex w-full flex-1 items-end">
                <div
                  className={`w-full ${s.tracking_gap ? "bg-[var(--text-3)] opacity-40" : "bg-[var(--accent)]"}`}
                  style={{ height: `${(s.sessions / maxSessions) * 100}%`, minHeight: s.sessions ? 2 : 0 }}
                  title={`${s.date}: ${s.sessions} sessions, ${s.conversions} key events${
                    s.brand_score !== null ? `, visibility ${s.brand_score}` : ""
                  }${s.tracking_gap ? " · tracking outage, undercounted" : ""}`}
                />
              </div>
            </div>
          ))}
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-[var(--text-3)]">
          <span>{d.series[0]?.date}</span>
          <span>{d.series[d.series.length - 1]?.date}</span>
        </div>
      </section>
    </main>
  );
}
