import Link from "next/link";
import type { Run, RunDetail } from "@/lib/api";
import { surfaceLabel } from "@/lib/viz";

const STATUS_STYLES: Record<Run["status"], string> = {
  pending: "bg-[var(--surface-2)] text-[var(--text)]",
  running: "border border-[var(--border-strong)] bg-[var(--surface-2)] text-[var(--text)]",
  complete: "border border-[var(--border)] bg-[var(--surface)] text-[var(--pos)]",
  failed: "border border-[var(--border)] bg-[var(--surface)] text-[var(--neg)]",
  gated: "border border-[var(--border)] bg-[var(--surface)] text-[var(--warn-t)]",
  capped: "border border-[var(--border)] bg-[var(--surface)] text-[var(--warn-t)]",
};

// Plain words for the stored status codes.
const STATUS_LABELS: Record<Run["status"], string> = {
  pending: "waiting",
  running: "running",
  complete: "complete",
  failed: "failed",
  gated: "not approved",
  capped: "spend cap reached",
};

export function StatusBadge({ status }: { status: Run["status"] }) {
  return (
    <span className={`whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function RunsTable({ runs, hrefBase }: { runs: Run[]; hrefBase: string }) {
  if (runs.length === 0) {
    return <p className="text-sm text-[var(--text-3)]">No runs yet.</p>;
  }
  return (
    <div className="card overflow-x-auto">
    <table className="bp-table w-full min-w-[760px] text-left">
      <thead>
        <tr>
          <th>Run</th>
          <th>Status</th>
          <th>Started by</th>
          <th>Engines</th>
          <th>Answers done / planned</th>
          <th>Cost</th>
          <th>Started</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id}>
            <td>
              <Link href={`${hrefBase}/${run.id}`} className="text-[var(--accent)] hover:underline">
                #{run.id}
              </Link>
            </td>
            <td>
              <StatusBadge status={run.status} />
            </td>
            <td className="text-[var(--text-2)]">{run.trigger}</td>
            <td className="text-xs text-[var(--text-2)]">
              {run.surface_set.map((x) => surfaceLabel(x)).join(", ")}
            </td>
            <td>
              {run.counts.completed ?? 0} / {run.counts.planned ?? 0}
              {(run.counts.withheld_by_cap ?? 0) > 0 && (
                <span className="ml-1 text-xs text-[var(--text-3)]">
                  ({run.counts.withheld_by_cap} held back by the spend cap)
                </span>
              )}
            </td>
            <td className="tabular-nums">${run.cost_usd.toFixed(2)}</td>
            <td className="whitespace-nowrap text-[var(--text-2)]">
              {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

/** `showCost`: admin only. Run cost is internal (it reveals the margin). */
export function RunDetailView({
  detail,
  hrefBase,
  showCost = false,
}: {
  detail: RunDetail;
  hrefBase: string;
  showCost?: boolean;
}) {
  const { run, results } = detail;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-center gap-3 text-sm text-[var(--text-2)]">
        <StatusBadge status={run.status} />
        <span>started by: {run.trigger}</span>
        {showCost && <span>cost: ${run.cost_usd.toFixed(4)}</span>}
        <span>citations: {run.counts.citations ?? 0}</span>
        {run.error && <span className="text-[var(--warn-t)]">{run.error}</span>}
      </div>
      <div className="card overflow-x-auto">
      <table className="bp-table w-full min-w-[820px] text-left">
        <thead>
          <tr>
            <th>Question</th>
            <th>Persona</th>
            <th>Engine</th>
            <th>Status</th>
            <th>Citations</th>
            <th>Latency</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {results.map(({ result, citations }) => (
            <tr key={result.id} className="align-top">
              <td className="max-w-xs">{result.query_text}</td>
              <td>
                {result.persona_name}
                <div className="text-xs text-[var(--text-3)]">{result.persona_segment}</div>
              </td>
              <td className="text-xs">{surfaceLabel(result.surface)}</td>
              <td>
                {result.status === "ok" ? (
                  <span className="text-[var(--pos)]">ok</span>
                ) : result.status === "blocked" ? (
                  // An anti-bot wall is missing data, not a brand-absence
                  // signal — show it distinctly, not as a hard error.
                  <span className="text-[var(--warn)]" title={result.error ?? ""}>
                    blocked
                  </span>
                ) : (
                  <span className="bp-neg text-xs" title={result.error ?? ""}>
                    error
                  </span>
                )}
              </td>
              <td>{citations.length}</td>
              <td className="whitespace-nowrap tabular-nums text-[var(--text-2)]">
                {result.latency_ms} ms
              </td>
              <td>
                {result.status === "ok" && (
                  <Link
                    href={`${hrefBase}/results/${result.id}`}
                    className="text-[var(--accent)] hover:underline"
                  >
                    <span className="whitespace-nowrap">View answer</span>
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </>
  );
}
