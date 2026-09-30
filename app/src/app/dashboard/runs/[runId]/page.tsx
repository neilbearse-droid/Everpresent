import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type RunDetail } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { RunDetailView } from "@/components/runs";

export default async function TenantRunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const [detail, me] = await Promise.all([
    apiFetch<RunDetail>(`/api/tenant/runs/${runId}`),
    apiFetch<Me>("/api/me"),
  ]);
  if (!detail.data) notFound();
  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Runs" isSuperadmin={me.data?.is_superadmin} />
      <Link href="/dashboard/runs" className="text-sm text-[var(--accent)] hover:underline">
        ← Runs
      </Link>
      <h1 className="mt-1 mb-4 text-2xl font-semibold tracking-tight">Run #{runId}</h1>
      <RunDetailView detail={detail.data} hrefBase={`/dashboard/runs/${runId}`} />
    </main>
  );
}
