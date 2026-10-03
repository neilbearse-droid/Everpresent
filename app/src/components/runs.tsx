import Link from "next/link";
import type { Run, RunDetail } from "@/lib/api";
import { surfaceLabel } from "@/lib/viz";

const STATUS_STYLES: Record<Run["status"], string> = {
  pending: "bg-[var(--surface-2)] text-[var(--text)]",
  running: "border border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--text)]",
  complete: "border border-[var(--border)] bg-[var(--surface)] text-[var(--pos)]",
  failed: "border border-[var(--border)] bg-[var(--surface)] text-[var(--neg)]",
  gated: "border border-[var(--border)] bg-[var(--surface)] text-[var(--warn-t)]",
  capped: "border border-[var(--border)] bg-[var(--surface)] text-[var(--warn-t)]",
};

export function StatusBadge({ status }: { status: Run["status"] }) {
  return (
    <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}>
      {status}
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
          <th>Trigger</th>
          <th>Surfaces</th>
          <th>Completed / planned</th>
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
                  ({run.counts.withheld_by_cap} capped)
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

export function RunDetailView({ detail, hrefBase }: { detail: RunDetail; hrefBase: string }) {
  const { run, results } = detail;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-center gap-3 text-sm text-[var(--text-2)]">
        <StatusBadge status={run.status} />
        <span>trigger: {run.trigger}</span>
        <span>cost: ${run.cost_usd.toFixed(4)}</span>
        <span>citations: {run.counts.citations ?? 0}</span>
        {run.error && <span className="text-[var(--warn-t)]">{run.error}</span>}
      </div>
      <div className="card overflow-x-auto">
      <table className="bp-table w-full min-w-[820px] text-left">
        <thead>
          <tr>
            <th>Query</th>
            <th>Persona</th>
            <th>Surface</th>
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
                    <span className="whitespace-nowrap">view response</span>
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
