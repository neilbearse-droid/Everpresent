import Link from "next/link";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { apiFetch, type Me, type TenantSummary } from "@/lib/api";

export default async function DashboardPage() {
  const [me, tenant] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<TenantSummary>("/api/tenant"),
  ]);

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-10 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">EverPresent</h1>
        <div className="flex items-center gap-4">
          {me.data?.is_superadmin && (
            <Link href="/admin" className="text-sm text-indigo-400 hover:underline">
              Admin
            </Link>
          )}
          <OrganizationSwitcher />
          <UserButton />
        </div>
      </header>

      {tenant.data ? (
        <>
          <section className="mb-6 rounded-lg border border-slate-700 bg-slate-900 p-6">
            <h2 className="text-lg font-medium">{tenant.data.name}</h2>
            <p className="mt-1 text-sm text-slate-400">
              Brand: {tenant.data.brand_name ?? "—"} · Status: {tenant.data.status} · AI
              processing: {tenant.data.ai_processing_approved ? "approved" : "gated"}
            </p>
          </section>
          <section className="grid gap-4 sm:grid-cols-3">
            {(
              [
                ["Personas", tenant.data.counts.personas],
                ["Queries", tenant.data.counts.queries],
                ["Competitors", tenant.data.counts.competitors],
              ] as const
            ).map(([label, n]) => (
              <div key={label} className="rounded-lg border border-slate-700 bg-slate-900 p-5">
                <div className="text-3xl font-semibold">{n}</div>
                <div className="mt-1 text-sm text-slate-400">{label}</div>
              </div>
            ))}
          </section>
          <p className="mt-8 text-sm text-slate-500">
            Visibility dashboards arrive with M3, after the first measurement runs (M2).
          </p>
        </>
      ) : (
        <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
          <h2 className="mb-2 text-lg font-medium">No organization selected</h2>
          <p className="text-sm text-slate-400">
            {tenant.status === 403
              ? "Pick an organization in the switcher above, or ask your EverPresent contact for an invite. (" +
                (tenant.error ?? "") +
                ")"
              : (tenant.error ?? "Could not reach the API.")}
          </p>
        </section>
      )}
    </main>
  );
}
