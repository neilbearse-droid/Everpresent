import { apiFetch, type Me, type Run } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { PageLead } from "@/components/page-lead";
import { RunsTable } from "@/components/runs";
import { fmtDate } from "@/lib/viz";

const STATUS_WORDS: Record<Run["status"], string> = {
  pending: "is waiting to start",
  running: "is running now",
  complete: "finished",
  failed: "failed",
  gated: "is waiting for approval",
  capped: "stopped at the spend cap",
};

export default async function TenantRunsPage() {
  const [runs, me] = await Promise.all([
    apiFetch<Run[]>("/api/tenant/runs"),
    apiFetch<Me>("/api/me"),
  ]);
  // The lead: what the latest run did and whether anything is needed. Runs
  // are scheduled, so the answer is usually nothing.
  const list = runs.data ?? [];
  const latest = list[0] ?? null;
  const lead = !latest
    ? {
        tells: "No runs yet.",
        act: "Nothing to do; runs are scheduled.",
        tone: "neutral" as const,
      }
    : {
        tells: (
          <>
            The latest run {STATUS_WORDS[latest.status]}
            {latest.status === "complete" && latest.finished_at ? <> on {fmtDate(latest.finished_at)}</> : <>, started {fmtDate(latest.started_at ?? latest.created_at)}</>}
            {latest.status === "complete" && latest.counts.ok !== undefined ? <>, {latest.counts.ok} answers</> : null}.
          </>
        ),
        act:
          latest.status === "failed"
            ? "Tell your EverPresent contact; they can resume it."
            : latest.status === "capped" || latest.status === "gated"
              ? "Ask your EverPresent contact to lift the hold."
              : latest.status === "running" || latest.status === "pending"
                ? "Nothing to do; the Overview updates when it finishes."
                : "Nothing to do; runs are scheduled.",
        tone: (latest.status === "failed" ? "bad" : "neutral") as "good" | "bad" | "neutral",
      };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Runs" isSuperadmin={me.data?.is_superadmin} />
      {runs.data ? (
        <>
          <PageLead {...lead} />
          <RunsTable runs={runs.data} hrefBase="/dashboard/runs" />
        </>
      ) : runs.status === 403 ? (
        <p className="text-sm text-[var(--text-2)]">No organization selected.</p>
      ) : (
        <p className="text-sm text-[var(--text-2)]">{runs.error}</p>
      )}
    </main>
  );
}
