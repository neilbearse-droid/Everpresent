import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type ReadinessPayload, type TenantDetail } from "@/lib/api";
import { setAIFeatures, setFanoutReprobe, setGovernance, setSearchCountry, toggleSurface } from "../actions";
import { AccessAuditPanel } from "./access-audit-panel";
import { BrandFactsPanel, type BrandFact } from "./brand-facts-panel";
import { ClerkOrgForm } from "./clerk-org-form";
import { CrawlPagesButton } from "./crawl-pages-button";
import { Ga4Form } from "./ga4-form";
import { ImportYamlForm } from "./import-yaml-form";
import { QueriesPanel } from "./queries-panel";
import { NotifyEmailsForm } from "./notify-emails-form";
import { PlanForm } from "./plan-form";
import { ScheduleForm } from "./schedule-form";
import { SpendCapForm } from "./spend-cap-form";

export default async function TenantAdminPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const me = await apiFetch<Me>("/api/me");
  if (!me.data?.is_superadmin) {
    return (
      <main className="mx-auto max-w-3xl px-8 py-16">
        <h1 className="text-xl font-semibold">Not authorized</h1>
      </main>
    );
  }

  const [detail, schedule, facts, readiness] = await Promise.all([
    apiFetch<TenantDetail>(`/api/admin/tenants/${slug}`),
    apiFetch<{ cron_expr: string; enabled: boolean; next_run_at: string | null } | null>(
      `/api/admin/tenants/${slug}/schedule`,
    ),
    apiFetch<BrandFact[]>(`/api/admin/tenants/${slug}/brand-facts`),
    apiFetch<ReadinessPayload>(`/api/admin/tenants/${slug}/readiness`),
  ]);
  if (detail.status === 404 || !detail.data) notFound();
  const { tenant, brand_profile, competitors, personas, queries, plans } = detail.data;
  const ready = readiness.data;
  // Fall back to the tenant's own approvals when the readiness call fails, so
  // the toggle never shows "off" (and flips the wrong way) on a transient error.
  const aiCheck = ready?.checks.find((c) => c.label.startsWith("Claude features"));
  const aiFeaturesOn =
    tenant.entity_extraction_enabled &&
    (aiCheck ? aiCheck.ok === true : (tenant.approved_utility_models ?? []).length > 0);
  const country = (tenant.aio_geo?.gl ?? "ca").toLowerCase();
  const countries: [string, string][] = [
    ["us", "United States"],
    ["ca", "Canada"],
    ["gb", "United Kingdom"],
    ["au", "Australia"],
  ];
  if (!countries.some(([code]) => code === country)) countries.push([country, "Current"]);

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <Link href="/admin" className="text-sm text-[var(--accent)] hover:underline">
            ← All tenants
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{tenant.name}</h1>
          <p className="text-sm text-[var(--text-2)]">
            {tenant.slug} · {tenant.status} · plan:{" "}
            <span className="font-medium text-[var(--text)]">
              {plans[tenant.plan]?.label ?? tenant.plan}
            </span>{" "}
            · brand: {brand_profile?.brand_name ?? "— no config imported —"}
          </p>
        </div>
        <Link
          href={`/admin/${tenant.slug}/runs`}
          className="rounded-md bg-[var(--ink)] px-4 py-2 text-sm font-medium text-[var(--ink-text)] hover:bg-[var(--ink-hover)]"
        >
          Runs →
        </Link>
      </header>

      {!ready && (
        <section className="card mb-6 p-4 text-sm text-[var(--text-2)]">
          Engine readiness couldn&apos;t load ({readiness.error ?? "unknown error"}). Reload
          to try again.
        </section>
      )}

      {/* Engine readiness: config + what the last run actually returned. */}
      {ready && (
        <section className="mb-6">
          <div className="blueprint grid-cols-1">
            <div>
              <div className="bp-bar">
                <span>Engine readiness</span>
                <span>
                  {ready.engines.filter((e) => e.verdict === "ready").length} /{" "}
                  {ready.engines.filter((e) => e.available).length} verified
                </span>
              </div>
              {ready.system && (
                <>
                  <div className="bp-bar">
                    <span>System</span>
                    <span>
                      {ready.system.every((c) => c.ok)
                        ? "All up"
                        : `${ready.system.filter((c) => !c.ok).length} down`}
                    </span>
                  </div>
                  <div className="grid gap-[2px] bg-[var(--line)] sm:grid-cols-3 lg:grid-cols-5">
                    {ready.system.map((c) => (
                      <div key={c.label} className="bg-[var(--surface)] p-3">
                        <div className="bp-label">{c.ok ? "✓ Up" : "✗ Down"}</div>
                        <div className={`mt-1 text-[13px] font-semibold ${c.ok ? "" : "bp-neg"}`}>
                          {c.label}
                        </div>
                        <p className="mt-1 text-[11.5px] text-[var(--text-2)]">{c.hint}</p>
                      </div>
                    ))}
                  </div>
                  <div className="bp-bar">
                    <span>Setup</span>
                    <span />
                  </div>
                </>
              )}
              <div className="grid gap-[2px] bg-[var(--line)] sm:grid-cols-2 lg:grid-cols-4">
                {ready.checks.map((c) => (
                  <div key={c.label} className="bg-[var(--surface)] p-3">
                    <div className="bp-label">{c.ok ? "✓ Done" : "✗ To do"}</div>
                    <div className={`mt-1 text-[13px] font-semibold ${c.ok ? "" : "bp-neg"}`}>
                      {c.label}
                    </div>
                    {!c.ok && <p className="mt-1 text-[11.5px] text-[var(--text-2)]">{c.hint}</p>}
                  </div>
                ))}
              </div>
              <table className="bp-table w-full">
                <thead>
                  <tr>
                    <th>Engine</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>What to do</th>
                    <th>Needs on the deployment</th>
                    <th>Last run</th>
                    <th className="text-right">Switch</th>
                  </tr>
                </thead>
                <tbody>
                  {ready.engines.map((e) => (
                    <tr key={e.code}>
                      <td>
                        <div className="font-semibold">{e.label}</div>
                        <div className="font-mono text-[10.5px] text-[var(--text-3)]">{e.code}</div>
                      </td>
                      <td className="bp-label">{e.mode}</td>
                      <td>
                        <span
                          className={`font-mono text-[11px] font-bold uppercase ${
                            e.verdict === "ready"
                              ? "bp-mark"
                              : ["missing_key", "blocked", "error", "withheld", "outside_plan"].includes(e.verdict)
                                ? "bp-neg"
                                : ""
                          }`}
                        >
                          {e.verdict.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td className="text-[12px]">{e.hint}</td>
                      <td className="text-[11.5px] text-[var(--text-2)]">
                        {e.needs.length ? e.needs.map((n) => <div key={n}>{n}</div>) : "—"}
                      </td>
                      <td className="font-mono text-[11px]">
                        {e.last_run.run_id ? (
                          <Link href={`/admin/${tenant.slug}/runs/${e.last_run.run_id}`} className="bp-link">
                            #{e.last_run.run_id}
                          </Link>
                        ) : (
                          "—"
                        )}
                        {e.last_run.run_id && (
                          <div className="text-[var(--text-2)]">
                            ok {e.last_run.ok} · blk {e.last_run.blocked} · err {e.last_run.error}
                          </div>
                        )}
                      </td>
                      <td className="text-right">
                        {e.available ? (
                          <form action={toggleSurface.bind(null, tenant.slug, e.code, !e.on)}>
                            <button className={`btn px-2.5 py-1 text-[11px] ${e.on ? "btn-primary" : "btn-ghost"}`}>
                              {e.on ? "On" : "Off"}
                            </button>
                          </form>
                        ) : (
                          <span className="bp-label">n/a</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      <section className="card mb-6 p-5">
        <h2 className="mb-1 font-medium">Plan</h2>
        <p className="mb-4 text-xs text-[var(--text-2)]">
          Caps the run matrix — prompts, personas, engines — the dual-query diagnosis, and the
          model tier. Applies on the next run; existing tenants default to Custom (uncapped).
        </p>
        <PlanForm slug={tenant.slug} current={tenant.plan} plans={plans} />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="mb-3 font-medium">Clerk organization</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Members of this Clerk org see this tenant's dashboards. Paste the org id
            (org_…) from the Clerk dashboard.
          </p>
          <ClerkOrgForm slug={tenant.slug} orgId={tenant.clerk_org_id ?? ""} />
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <h3 className="mb-1 text-sm font-medium">GA4 property (Outcome attribution)</h3>
            <p className="mb-3 text-xs text-[var(--text-2)]">
              Numeric GA4 property id. Grant the EverPresent service account{" "}
              <span className="font-mono">Viewer</span> on this property, then AI-referral
              traffic populates the Outcome tab nightly.
            </p>
            <Ga4Form slug={tenant.slug} propertyId={tenant.ga4_property_id ?? ""} />
          </div>
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Governance</h2>
          <p className="mb-3 text-sm">
            AI processing:{" "}
            <span className={tenant.ai_processing_approved ? "text-[var(--pos)]" : "text-[var(--warn-t)]"}>
              {tenant.ai_processing_approved ? "approved" : "gated"}
            </span>
          </p>
          <form action={setGovernance.bind(null, tenant.slug, !tenant.ai_processing_approved)}>
            <button className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-2)]">
              {tenant.ai_processing_approved ? "Revoke approval" : "Approve AI processing"}
            </button>
          </form>
          <p className="mt-3 text-xs text-[var(--text-3)]">
            Runs for a gated tenant are recorded with status <code>gated</code>, never
            silently skipped.
          </p>
          <SpendCapForm slug={tenant.slug} cap={tenant.monthly_spend_cap_usd} />
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <p className="mb-2 text-sm">Search country</p>
            <form action={setSearchCountry.bind(null, tenant.slug)} className="flex gap-2">
              <select
                name="country"
                defaultValue={country}
                className="field px-2 py-1.5 text-[12px]"
              >
                {countries.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name} ({code.toUpperCase()})
                  </option>
                ))}
              </select>
              <button className="btn btn-ghost px-3 py-1.5 text-[12px]">Save</button>
            </form>
            <p className="mt-2 text-xs text-[var(--text-3)]">
              Where Google AI Overviews and the browser engines search from. Match the client&apos;s
              market.
            </p>
          </div>
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <p className="mb-3 text-sm">
              Claude features:{" "}
              <span className="font-semibold">{aiFeaturesOn ? "on" : "off"}</span>
            </p>
            <form action={setAIFeatures.bind(null, tenant.slug, !aiFeaturesOn)}>
              <button className="btn btn-ghost px-3 py-2 text-[12px]">
                {aiFeaturesOn ? "Turn off Claude features" : "Turn on Claude features"}
              </button>
            </form>
            <p className="mt-3 text-xs text-[var(--text-3)]">
              Powers the Whitespace page (names the AI recommends that you don&apos;t track) and the
              corrective-content and brief buttons. Uses ANTHROPIC_API_KEY; costs count toward the
              monthly cap.
            </p>
          </div>
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <p className="mb-3 text-sm">
              Fan-out re-probe:{" "}
              <span className={tenant.fanout_reprobe_enabled ? "text-[var(--pos)]" : "text-[var(--text-2)]"}>
                {tenant.fanout_reprobe_enabled ? "on" : "off"}
              </span>
            </p>
            <form action={setFanoutReprobe.bind(null, tenant.slug, !tenant.fanout_reprobe_enabled)}>
              <button className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-2)]">
                {tenant.fanout_reprobe_enabled ? "Turn off re-probe" : "Turn on re-probe"}
              </button>
            </form>
            <p className="mt-3 text-xs text-[var(--text-3)]">
              After each run, re-runs the top fan-out sub-queries on the engine that issued them
              to measure whether the brand appears in each one.{" "}
              {(() => {
                const lim = plans[tenant.plan];
                return lim && lim.shard_probes_per_run > 0
                  ? `This plan allows ${lim.shard_probes_per_prompt} per prompt, ${lim.shard_probes_per_run} per run.`
                  : "This plan includes the map only — no re-probes.";
              })()}{" "}
              Spend counts toward the monthly cap.
            </p>
          </div>
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Run schedule</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Scheduled runs use the tenant's current surfaces and governance state at fire
            time.
            {schedule.data?.next_run_at &&
              ` Next run: ${new Date(schedule.data.next_run_at).toLocaleString()} UTC.`}
          </p>
          <ScheduleForm
            slug={tenant.slug}
            cronExpr={schedule.data?.cron_expr ?? ""}
            enabled={schedule.data?.enabled ?? true}
          />
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Notifications</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Run-completion reports (PDF + CSV) go to these addresses. Comma-separated.
          </p>
          <NotifyEmailsForm slug={tenant.slug} emails={tenant.notify_emails.join(", ")} />
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">AI access audit</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Probes the brand's domains the way the answer engines do: robots.txt rules for
            each AI crawler, CDN bot-blocking, llms.txt, and homepage structured data. A
            surprising share of visibility gaps are a one-line config fix.
          </p>
          <AccessAuditPanel slug={tenant.slug} />
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <h3 className="mb-1 text-sm font-medium">Power Pages presence crawl</h3>
            <p className="mb-3 text-xs text-[var(--text-2)]">
              Fetches the top third-party pages the engines cite and checks whether the brand
              is actually named on each. Runs nightly; queue one now after a fresh run.
            </p>
            <CrawlPagesButton slug={tenant.slug} />
          </div>
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Brand fact sheet — accuracy monitoring</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Ground-truth facts the answer engines must get right. Each run checks every answer
            against these and flags contradictions on the Scorecard — the highest-stakes error
            for a credentialed or regulated brand. Numeric facts catch wrong figures near the
            subject; disallowed facts catch a phrase that must never appear.
          </p>
          <BrandFactsPanel slug={tenant.slug} facts={facts.data ?? []} />
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Import config YAML</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Replace-semantics: brand, competitors, personas, queries, and surface
            enablement are swapped wholesale.
          </p>
          <ImportYamlForm slug={tenant.slug} />
        </section>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <section className="card p-5">
          <h2 className="mb-3 font-medium">Personas ({personas.length})</h2>
          <ul className="space-y-3">
            {personas.map((p) => (
              <li key={p.id} className="text-sm">
                <div className="font-medium">{p.name}</div>
                <div className="text-xs text-[var(--text-3)]">{p.segment_tag}</div>
              </li>
            ))}
          </ul>
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Competitors ({competitors.length})</h2>
          <ul className="space-y-2">
            {competitors.map((c) => (
              <li key={c.id} className="text-sm">
                {c.name}
                <span className="ml-2 text-xs text-[var(--text-3)]">{c.domains.join(", ")}</span>
              </li>
            ))}
          </ul>
        </section>

        <QueriesPanel slug={tenant.slug} queries={queries} />
      </div>
    </main>
  );
}
