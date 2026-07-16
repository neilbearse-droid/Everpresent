import Link from "next/link";
import type { Run, RunDetail } from "@/lib/api";
import { surfaceLabel } from "@/lib/viz";

const STATUS_STYLES: Record<Run["status"], string> = {
  pending: "bg-slate-700 text-slate-200",
  running: "bg-sky-700 text-white",
  complete: "bg-emerald-700 text-white",
  failed: "bg-red-800 text-white",
  gated: "bg-amber-700 text-white",
  capped: "bg-orange-700 text-white",
};

export function StatusBadge({ status }: { status: Run["status"] }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}>
      {status}
    </span>
  );
}

export function RunsTable({ runs, hrefBase }: { runs: Run[]; hrefBase: string }) {
  if (runs.length === 0) {
    return <p className="text-sm text-slate-500">No runs yet.</p>;
  }
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-slate-400">
        <tr>
          <th className="py-2">Run</th>
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
          <tr key={run.id} className="border-t border-[var(--border)]">
            <td className="py-3">
              <Link href={`${hrefBase}/${run.id}`} className="text-indigo-400 hover:underline">
                #{run.id}
              </Link>
            </td>
            <td>
              <StatusBadge status={run.status} />
            </td>
            <td className="text-slate-400">{run.trigger}</td>
            <td className="font-mono text-xs text-slate-400">{run.surface_set.join(", ")}</td>
            <td>
              {run.counts.completed ?? 0} / {run.counts.planned ?? 0}
              {(run.counts.withheld_by_cap ?? 0) > 0 && (
                <span className="ml-1 text-xs text-orange-400">
                  ({run.counts.withheld_by_cap} capped)
                </span>
              )}
            </td>
            <td>${run.cost_usd.toFixed(4)}</td>
            <td className="text-slate-400">
              {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RunDetailView({ detail, hrefBase }: { detail: RunDetail; hrefBase: string }) {
  const { run, results } = detail;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-center gap-3 text-sm text-slate-400">
        <StatusBadge status={run.status} />
        <span>trigger: {run.trigger}</span>
        <span>cost: ${run.cost_usd.toFixed(4)}</span>
        <span>citations: {run.counts.citations ?? 0}</span>
        {run.error && <span className="text-amber-400">{run.error}</span>}
      </div>
      <table className="w-full text-left text-sm">
        <thead className="text-slate-400">
          <tr>
            <th className="py-2">Query</th>
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
            <tr key={result.id} className="border-t border-[var(--border)] align-top">
              <td className="max-w-xs py-3 pr-3">{result.query_text}</td>
              <td className="pr-3">
                {result.persona_name}
                <div className="text-xs text-slate-500">{result.persona_segment}</div>
              </td>
              <td className="text-xs">{surfaceLabel(result.surface)}</td>
              <td>
                {result.status === "ok" ? (
                  <span className="text-emerald-400">ok</span>
                ) : (
                  <span className="text-red-400" title={result.error ?? ""}>
                    error
                  </span>
                )}
              </td>
              <td>{citations.length}</td>
              <td className="text-slate-400">{result.latency_ms} ms</td>
              <td>
                {result.status === "ok" && (
                  <Link
                    href={`${hrefBase}/results/${result.id}`}
                    className="text-indigo-400 hover:underline"
                  >
                    view response
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
