import { apiFetch, type Me, type Run } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { RunsTable } from "@/components/runs";

export default async function TenantRunsPage() {
  const [runs, me] = await Promise.all([
    apiFetch<Run[]>("/api/tenant/runs"),
    apiFetch<Me>("/api/me"),
  ]);
  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Runs" isSuperadmin={me.data?.is_superadmin} />
      <h1 className="mt-1 mb-6 text-2xl font-semibold tracking-tight">Runs</h1>
      {runs.data ? (
        <RunsTable runs={runs.data} hrefBase="/dashboard/runs" />
      ) : runs.status === 403 ? (
        <p className="text-sm text-[var(--text-2)]">
          No organization selected. Choose one from the switcher at the top right.
        </p>
      ) : (
        <p className="text-sm text-[var(--text-2)]">{runs.error}</p>
      )}
    </main>
  );
}
