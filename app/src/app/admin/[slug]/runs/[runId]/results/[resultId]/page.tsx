import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type RawEnvelope } from "@/lib/api";
import { RawResponseView } from "@/components/raw-response";

export default async function AdminRawResultPage({
  params,
}: {
  params: Promise<{ slug: string; runId: string; resultId: string }>;
}) {
  const { slug, runId, resultId } = await params;
  const me = await apiFetch<Me>("/api/me");
  if (!me.data?.is_superadmin) {
    return (
      <main className="mx-auto max-w-3xl px-8 py-16">
        <h1 className="text-xl font-semibold">Not authorized</h1>
      </main>
    );
  }
  const raw = await apiFetch<RawEnvelope>(`/api/admin/results/${resultId}/raw`);
  if (!raw.data) notFound();

  return (
    <main className="mx-auto max-w-4xl px-8 py-10">
      <Link
        href={`/admin/${slug}/runs/${runId}`}
        className="text-sm text-indigo-400 hover:underline"
      >
        ← Run #{runId}
      </Link>
      <h1 className="mt-1 mb-6 text-2xl font-semibold tracking-tight">Result #{resultId}</h1>
      <RawResponseView envelope={raw.data} />
    </main>
  );
}
