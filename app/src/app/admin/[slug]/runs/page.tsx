import Link from "next/link";
import { apiFetch, type AdminRunsPayload, type Me } from "@/lib/api";
import { RunsTable } from "@/components/runs";
import { TriggerRunButton } from "./trigger-run-button";

export default async function AdminRunsPage({
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
  const payload = await apiFetch<AdminRunsPayload>(`/api/admin/tenants/${slug}/runs`);
  if (!payload.data) {
    return <main className="mx-auto max-w-3xl px-8 py-16">{payload.error}</main>;
  }

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <Link href={`/admin/${slug}`} className="text-sm text-indigo-400 hover:underline">
            ← {slug}
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Runs — {slug}</h1>
          <p className="text-sm text-slate-400">
            Month spend: ${payload.data.month_spend_usd.toFixed(2)} / cap $
            {payload.data.monthly_spend_cap_usd.toFixed(2)}
            {payload.data.month_spend_usd >= 0.8 * payload.data.monthly_spend_cap_usd && (
              <span className="ml-2 text-amber-400">▲ over 80% of cap</span>
            )}
          </p>
        </div>
        <TriggerRunButton slug={slug} />
      </header>
      <RunsTable runs={payload.data.runs} hrefBase={`/admin/${slug}/runs`} />
    </main>
  );
}
