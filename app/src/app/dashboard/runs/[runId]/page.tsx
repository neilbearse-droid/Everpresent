import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type RunDetail } from "@/lib/api";
import { RunDetailView } from "@/components/runs";

export default async function TenantRunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const detail = await apiFetch<RunDetail>(`/api/tenant/runs/${runId}`);
  if (!detail.data) notFound();
  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <Link href="/dashboard/runs" className="text-sm text-indigo-400 hover:underline">
        ← Runs
      </Link>
      <h1 className="mt-1 mb-4 text-2xl font-semibold tracking-tight">Run #{runId}</h1>
      <RunDetailView detail={detail.data} hrefBase={`/dashboard/runs/${runId}`} />
    </main>
  );
}
