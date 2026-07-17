import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type TenantDetail } from "@/lib/api";
import { surfaceLabel } from "@/lib/viz";
import { setGovernance, toggleSurface } from "../actions";
import { AccessAuditPanel } from "./access-audit-panel";
import { ClerkOrgForm } from "./clerk-org-form";
import { Ga4Form } from "./ga4-form";
import { ImportYamlForm } from "./import-yaml-form";
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

  const [detail, schedule] = await Promise.all([
    apiFetch<TenantDetail>(`/api/admin/tenants/${slug}`),
    apiFetch<{ cron_expr: string; enabled: boolean; next_run_at: string | null } | null>(
      `/api/admin/tenants/${slug}/schedule`,
    ),
  ]);
  if (detail.status === 404 || !detail.data) notFound();
  const { tenant, brand_profile, competitors, personas, queries, surfaces, plans } = detail.data;

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
          className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          Runs →
        </Link>
      </header>

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
        </section>

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Surfaces</h2>
          <ul className="space-y-2">
            {surfaces.map((s) => (
              <li key={s.code} className="flex items-center justify-between text-sm">
                <span>
                  {surfaceLabel(s.code)}
                  <span className="ml-2 font-mono text-xs text-[var(--text-3)]">{s.code}</span>
                </span>
                <form action={toggleSurface.bind(null, tenant.slug, s.code, !s.enabled)}>
                  <button
                    className={`rounded-md px-3 py-1 text-xs font-medium ${
                      s.enabled
                        ? "bg-emerald-600 text-white hover:bg-emerald-500"
                        : "border border-[var(--border)] text-[var(--text-2)] hover:bg-[var(--surface-2)]"
                    }`}
                  >
                    {s.enabled ? "enabled" : "disabled"}
                  </button>
                </form>
              </li>
            ))}
            {surfaces.length === 0 && (
              <li className="text-sm text-[var(--text-3)]">No surfaces yet — import a config.</li>
            )}
          </ul>
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

        <section className="card p-5">
          <h2 className="mb-3 font-medium">Queries ({queries.length})</h2>
          <ul className="space-y-2">
            {queries.map((q) => (
              <li key={q.id} className="text-sm">
                {q.text}
                <span className="ml-2 text-xs text-[var(--text-3)]">{q.corpus_tag}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
