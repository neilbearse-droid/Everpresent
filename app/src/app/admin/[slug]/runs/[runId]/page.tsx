import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type RunDetail } from "@/lib/api";
import { RunDetailView } from "@/components/runs";

export default async function AdminRunDetailPage({
  params,
}: {
  params: Promise<{ slug: string; runId: string }>;
}) {
  const { slug, runId } = await params;
  const me = await apiFetch<Me>("/api/me");
  if (!me.data?.is_superadmin) {
    return (
      <main className="mx-auto max-w-3xl px-8 py-16">
        <h1 className="text-xl font-semibold">Not authorized</h1>
      </main>
    );
  }
  const detail = await apiFetch<RunDetail>(`/api/admin/runs/${runId}`);
  if (!detail.data) notFound();

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <Link href={`/admin/${slug}/runs`} className="text-sm text-indigo-400 hover:underline">
        ← Runs
      </Link>
      <h1 className="mt-1 mb-4 text-2xl font-semibold tracking-tight">
        Run #{runId} — {slug}
      </h1>
      <RunDetailView detail={detail.data} hrefBase={`/admin/${slug}/runs/${runId}`} />
    </main>
  );
}
