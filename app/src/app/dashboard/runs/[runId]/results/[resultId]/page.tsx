import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type RawEnvelope } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { RawResponseView } from "@/components/raw-response";

export default async function TenantRawResultPage({
  params,
}: {
  params: Promise<{ runId: string; resultId: string }>;
}) {
  const { runId, resultId } = await params;
  const [raw, me] = await Promise.all([
    apiFetch<RawEnvelope>(`/api/tenant/results/${resultId}/raw`),
    apiFetch<Me>("/api/me"),
  ]);
  if (!raw.data) notFound();
  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Runs" isSuperadmin={me.data?.is_superadmin} />
      <Link href={`/dashboard/runs/${runId}`} className="text-sm text-[var(--accent)] hover:underline">
        ← Run #{runId}
      </Link>
      <h1 className="mt-1 mb-6 text-2xl font-semibold tracking-tight">Result #{resultId}</h1>
      <RawResponseView envelope={raw.data} />
    </main>
  );
}
