import Link from "next/link";
import { apiFetch, type Run } from "@/lib/api";
import { RunsTable } from "@/components/runs";

export default async function TenantRunsPage() {
  const runs = await apiFetch<Run[]>("/api/tenant/runs");
  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <Link href="/dashboard" className="text-sm text-indigo-400 hover:underline">
        ← Dashboard
      </Link>
      <h1 className="mt-1 mb-6 text-2xl font-semibold tracking-tight">Runs</h1>
      {runs.data ? (
        <RunsTable runs={runs.data} hrefBase="/dashboard/runs" />
      ) : runs.status === 403 ? (
        <p className="text-sm text-slate-400">
          No organization selected — pick one in the switcher on the Overview tab to see its
          runs.
        </p>
      ) : (
        <p className="text-sm text-slate-400">{runs.error}</p>
      )}
    </main>
  );
}
