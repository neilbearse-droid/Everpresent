import { apiFetch, type Me, type OutcomePayload } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { HBars } from "@/components/charts";

export default async function OutcomePage() {
  const [me, out] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<OutcomePayload>("/api/tenant/outcome"),
  ]);
  if (out.status === 403) {
    return <NoOrgNotice active="Outcome" isSuperadmin={me.data?.is_superadmin} detail={out.error} />;
  }
  const d = out.data;

  const notReady = (title: string, body: string) => (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Outcome" isSuperadmin={me.data?.is_superadmin} />
      <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-2 text-lg font-medium">{title}</h2>
        <p className="max-w-xl text-sm text-slate-400">{body}</p>
      </section>
    </main>
  );

  if (!d || !d.connected) {
    return notReady(
      "Connect Google Analytics",
      "Add this tenant's GA4 property id in the admin panel and grant the EverPresent service account Viewer access. Once connected, AI-referred traffic (ChatGPT, Perplexity, Claude, Gemini…) is pulled nightly and shown here against your visibility trend.",
    );
  }
  if (!d.has_data) {
    return notReady(
      "Connected — waiting for the first pull",
      "GA4 is linked. AI-referral traffic appears after the nightly refresh runs (or on the next scheduled pull). Traffic is matched by utm_source and referrer across the major answer engines.",
    );
  }

  const maxSessions = Math.max(...d.series.map((s) => s.sessions), 1);
  const scored = d.series.filter((s) => s.brand_score !== null);

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Outcome" isSuperadmin={me.data?.is_superadmin} />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
          <div className="text-3xl font-semibold tabular-nums">{d.totals.sessions}</div>
          <div className="mt-1 text-sm text-slate-400">AI-referred sessions</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
          <div className="text-3xl font-semibold tabular-nums">{d.totals.conversions}</div>
          <div className="mt-1 text-sm text-slate-400">Key events from AI referrals</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
          <div className="text-3xl font-semibold tabular-nums">{d.engine_totals.length}</div>
          <div className="mt-1 text-sm text-slate-400">Answer engines sending traffic</div>
        </div>
      </div>

      <section className="mb-6 rounded-lg border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-4 text-sm font-medium text-slate-400">
          AI-referred sessions by engine — where the visits come from
        </h2>
        <HBars
          items={d.engine_totals.map((e) => ({
            label: `${e.engine} · ${e.conversions} key events`,
            value: e.sessions,
            color: "#818cf8",
          }))}
          max={Math.max(...d.engine_totals.map((e) => e.sessions), 1)}
        />
      </section>

      <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-1 text-sm font-medium text-slate-400">
          AI referrals vs visibility — does being cited move the business?
        </h2>
        <p className="mb-4 text-xs text-slate-500">
          Daily AI-referred sessions (bars) alongside your brand-visibility score (line) for
          days a run measured it. When visibility rises and referrals follow, that's the story
          for the boardroom.
        </p>
        <div className="flex items-end gap-1" style={{ height: 140 }}>
          {d.series.map((s) => (
            <div key={s.date} className="flex flex-1 flex-col items-center justify-end gap-1">
              {s.brand_score !== null && (
                <span className="text-[9px] text-emerald-400">{s.brand_score}</span>
              )}
              <div
                className="w-full rounded-t bg-indigo-500"
                style={{ height: `${(s.sessions / maxSessions) * 100}%`, minHeight: s.sessions ? 2 : 0 }}
                title={`${s.date}: ${s.sessions} sessions, ${s.conversions} key events${
                  s.brand_score !== null ? `, visibility ${s.brand_score}` : ""
                }`}
              />
            </div>
          ))}
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-slate-600">
          <span>{d.series[0]?.date}</span>
          <span>{d.series[d.series.length - 1]?.date}</span>
        </div>
        {scored.length < 2 && (
          <p className="mt-3 text-xs text-slate-500">
            The visibility overlay sharpens as more measured days accumulate.
          </p>
        )}
      </section>
    </main>
  );
}
