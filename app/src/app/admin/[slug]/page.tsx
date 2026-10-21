import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type ReadinessPayload, type TenantDetail } from "@/lib/api";
import { setAIFeatures, setFanoutReprobe, setGovernance, setSearchCountry, toggleSurface } from "../actions";
import { AccessAuditPanel } from "./access-audit-panel";
import { BrandFactsPanel, type BrandFact } from "./brand-facts-panel";
import { ClerkOrgForm } from "./clerk-org-form";
import { CrawlPagesButton } from "./crawl-pages-button";
import { ReprocessButton } from "./reprocess-button";
import { EngineCheckButton } from "./engine-check-button";
import { Ga4Form } from "./ga4-form";
import { ImportYamlForm, type BundledSeed } from "./import-yaml-form";
import { ImportCapturesForm } from "./import-captures-form";
import { AgentTokenForm } from "./agent-token-form";
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
      <main className="mx-auto max-w-3xl px-4 py-16 sm:px-8">
        <h1 className="text-xl font-semibold">Not authorized</h1>
      </main>
    );
  }

  const [detail, schedule, facts, readiness, seeds] = await Promise.all([
    apiFetch<TenantDetail>(`/api/admin/tenants/${slug}`),
    apiFetch<{ cron_expr: string; enabled: boolean; next_run_at: string | null } | null>(
      `/api/admin/tenants/${slug}/schedule`,
    ),
    apiFetch<BrandFact[]>(`/api/admin/tenants/${slug}/brand-facts`),
    apiFetch<ReadinessPayload>(`/api/admin/tenants/${slug}/readiness`),
    apiFetch<BundledSeed[]>("/api/admin/seeds"),
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
  // Plain names for the engine types the readiness API reports.
  const engineType: Record<string, string> = {
    API: "API",
    Browser: "Browser",
    SERP: "Google results",
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-8">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <Link href="/admin" className="text-sm text-[var(--accent)] hover:underline">
            ← All clients
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{tenant.name}</h1>
          <p className="text-sm text-[var(--text-2)]">
            {tenant.slug} · {tenant.status} · plan:{" "}
            <span className="font-medium text-[var(--text)]">
              {plans[tenant.plan]?.label ?? tenant.plan}
            </span>{" "}
            · brand: {brand_profile?.brand_name ?? "no config imported"}
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
                  {ready.engines.filter((e) => e.verdict === "ready" || e.verdict === "check_ok").length} /{" "}
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
                  <div className="grid grid-cols-1 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-5">
                    {ready.system.map((c) => (
                      <div key={c.label} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                        <div className={`text-[13px] font-semibold ${c.ok ? "" : "bp-neg"}`}>
                          {c.label}
                        </div>
                        <div className="mt-0.5 text-[12px] text-[var(--text-3)]">{c.ok ? "Up" : "Down"}</div>
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
              <div className="grid grid-cols-1 gap-2 p-3 sm:grid-cols-2 lg:grid-cols-4">
                {ready.checks.map((c) => (
                  <div key={c.label} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                    <div className={`text-[13px] font-semibold ${c.ok ? "" : "bp-neg"}`}>
                      {c.label}
                    </div>
                    <div className="mt-0.5 text-[12px] text-[var(--text-3)]">{c.ok ? "Done" : "To do"}</div>
                    {!c.ok && <p className="mt-1 text-[11.5px] text-[var(--text-2)]">{c.hint}</p>}
                  </div>
                ))}
              </div>
              <EngineCheckButton
                slug={tenant.slug}
                engines={ready.engines
                  .filter((e) => e.on && e.available && e.verdict !== "outside_plan")
                  .map((e) => ({ code: e.code, at: e.check?.at ?? null }))}
              />
              <div className="overflow-x-auto"><table className="bp-table w-full min-w-[680px]">
                <thead>
                  <tr>
                    <th>Engine</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>What to do</th>
                    <th>Server settings needed</th>
                    <th>Last run</th>
                    <th className="text-right">On / off</th>
                  </tr>
                </thead>
                <tbody>
                  {ready.engines.map((e) => (
                    <tr key={e.code}>
                      <td>
                        <div className="font-semibold">{e.label}</div>
                        <div className="text-[11px] text-[var(--text-3)]">{e.code}</div>
                      </td>
                      <td className="whitespace-nowrap text-[12px] text-[var(--text-2)]">
                        {engineType[e.mode] ?? e.mode}
                      </td>
                      <td>
                        <span
                          className={`text-[12px] font-medium ${
                            e.verdict === "ready" || e.verdict === "check_ok"
                              ? "bp-mark"
                              : ["missing_key", "blocked", "error", "withheld", "outside_plan",
                                 "check_failed", "check_parse"].includes(e.verdict)
                                ? "bp-neg"
                                : ""
                          }`}
                        >
                          {e.verdict === "check_ok"
                            ? "verified live"
                            : e.verdict === "check_failed"
                              ? "live check failed"
                              : e.verdict === "check_parse"
                                ? "couldn't read the answer"
                                : e.verdict.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td className="text-[12px]">
                        {e.hint}
                        {e.check && (
                          <div className="mt-1 text-[11.5px] text-[var(--text-3)]">
                            Live check {new Date(e.check.at).toLocaleString()}: {e.check.status.replaceAll("_", " ")}
                            {e.check.latency_ms ? ` · ${(e.check.latency_ms / 1000).toFixed(1)}s` : ""}
                            {e.check.model ? ` · ${e.check.model}` : ""}
                            {e.check.citations ? ` · ${e.check.citations} sources` : ""}
                            {e.check.detail && <div className="mt-0.5 break-words">{e.check.detail}</div>}
                          </div>
                        )}
                      </td>
                      <td className="text-[11.5px] text-[var(--text-2)]">
                        {e.needs.length ? e.needs.map((n) => <div key={n}>{n}</div>) : "—"}
                      </td>
                      <td className="whitespace-nowrap text-[12px] tabular-nums">
                        {e.last_run.run_id ? (
                          <Link href={`/admin/${tenant.slug}/runs/${e.last_run.run_id}`} className="bp-link">
                            #{e.last_run.run_id}
                          </Link>
                        ) : (
                          "—"
                        )}
                        {e.last_run.run_id && (
                          <div className="text-[var(--text-2)]">
                            {e.last_run.ok} ok · {e.last_run.blocked} blocked · {e.last_run.error} failed
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
                          <span className="text-[12px] text-[var(--text-3)]">Not available</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </div>
          </div>
        </section>
      )}

      <section className="card mb-6 p-5">
        <h2 className="mb-1 font-medium">Plan</h2>
        <p className="mb-4 text-xs text-[var(--text-2)]">
          Sets how many questions, personas and engines each run covers, whether each question is
          also asked with web search turned off, and which model of each API engine answers.
          Takes effect on the next run. Existing clients default to Custom, which has no limits.
        </p>
        <PlanForm slug={tenant.slug} current={tenant.plan} plans={plans} />
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="mb-3 font-medium">Clerk organization</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Members of this Clerk organization see this client&apos;s dashboards. Paste the
            organization ID (it starts with org_) from the Clerk dashboard.
          </p>
          <ClerkOrgForm slug={tenant.slug} orgId={tenant.clerk_org_id ?? ""} />
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <h3 className="mb-1 text-sm font-medium">GA4 property (for the Outcome page)</h3>
            <p className="mb-3 text-xs text-[var(--text-2)]">
              The GA4 property ID, digits only. Give the EverPresent service account{" "}
              <span className="font-mono">Viewer</span> access to the property, and visits that
              come from AI assistants appear on the Outcome page each night.
            </p>
            <Ga4Form slug={tenant.slug} propertyId={tenant.ga4_property_id ?? ""} />
          </div>
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Governance</h2>
          <p className="mb-3 text-sm">
            AI processing:{" "}
            <span className={tenant.ai_processing_approved ? "text-[var(--pos)]" : "text-[var(--warn-t)]"}>
              {tenant.ai_processing_approved ? "approved" : "not approved"}
            </span>
          </p>
          <form action={setGovernance.bind(null, tenant.slug, !tenant.ai_processing_approved)}>
            <button className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-2)]">
              {tenant.ai_processing_approved ? "Revoke approval" : "Approve AI processing"}
            </button>
          </form>
          <p className="mt-3 text-xs text-[var(--text-3)]">
            Runs for a client without approval are still logged, with the status
            &ldquo;not approved&rdquo;.
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
              Needed for the Whitespace page (brands the AI recommends that you don&apos;t track)
              and the buttons that draft corrections and briefs. Uses the ANTHROPIC_API_KEY
              setting, and the cost counts toward the monthly cap.
            </p>
          </div>
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <p className="mb-3 text-sm">
              Re-check sub-searches:{" "}
              <span className={tenant.fanout_reprobe_enabled ? "text-[var(--pos)]" : "text-[var(--text-2)]"}>
                {tenant.fanout_reprobe_enabled ? "on" : "off"}
              </span>
            </p>
            <form action={setFanoutReprobe.bind(null, tenant.slug, !tenant.fanout_reprobe_enabled)}>
              <button className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-2)]">
                {tenant.fanout_reprobe_enabled ? "Turn off re-checks" : "Turn on re-checks"}
              </button>
            </form>
            <p className="mt-3 text-xs text-[var(--text-3)]">
              Before answering, an engine may run several web searches of its own
              (sub-searches). After each run, this repeats the main sub-searches on the engine
              that ran them, to see whether the brand shows up in each one.{" "}
              {(() => {
                const lim = plans[tenant.plan];
                return lim && lim.shard_probes_per_run > 0
                  ? `This plan allows ${lim.shard_probes_per_prompt} per question and ${lim.shard_probes_per_run} per run.`
                  : "This plan lists the sub-searches but doesn't re-check them.";
              })()}{" "}
              The cost counts toward the monthly cap.
            </p>
          </div>
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Run schedule</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Each scheduled run uses the client&apos;s engines and approval status as they are
            when the run starts.
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
            When a run finishes, a report (PDF and CSV) goes to these addresses. Separate them
            with commas.
          </p>
          <NotifyEmailsForm slug={tenant.slug} emails={tenant.notify_emails.join(", ")} />
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">AI access audit</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Checks the brand&apos;s websites the way AI engines reach them: robots.txt rules for
            each AI crawler, bot blocking at the CDN, llms.txt, and structured data on the
            homepage.
          </p>
          <AccessAuditPanel slug={tenant.slug} />
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <h3 className="mb-1 text-sm font-medium">Power pages check</h3>
            <p className="mb-3 text-xs text-[var(--text-2)]">
              Opens the third-party pages the engines cite most and checks whether each one
              names the brand. Runs every night; start one now after a new run.
            </p>
            <CrawlPagesButton slug={tenant.slug} />
          </div>
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <h3 className="mb-1 text-sm font-medium">Reprocess history</h3>
            <p className="mb-3 text-xs text-[var(--text-2)]">
              Reads every stored answer again with the current checks (sub-searches, ads, fact
              checks). It doesn&apos;t buy new answers.
            </p>
            <ReprocessButton slug={tenant.slug} />
          </div>
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Brand facts (accuracy checks)</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Facts the AI engines need to get right. Each run checks every answer against them
            and flags contradictions on the Scorecard. A numeric fact catches a wrong figure near
            its subject term; a disallowed fact catches a phrase that must never appear.
          </p>
          <BrandFactsPanel slug={tenant.slug} facts={facts.data ?? []} />
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Import a config (YAML)</h2>
          <p className="mb-3 text-xs text-[var(--text-2)]">
            Importing replaces the client&apos;s brand, competitors, personas, questions and
            engine settings.
          </p>
          <ImportYamlForm slug={tenant.slug} seeds={seeds.data ?? []} />
          <div className="mt-6 border-t border-[var(--border)] pt-4">
            <p className="mb-2 text-sm">Answers from a capture vendor</p>
            <ImportCapturesForm slug={tenant.slug} />
          </div>
          <div className="mt-6 border-t border-[var(--border)] pt-4">
            <p className="mb-2 text-sm">AI bot logs (for the AI Agents page)</p>
            <AgentTokenForm slug={tenant.slug} />
          </div>
        </section>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
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
