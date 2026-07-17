"use client";

import { useActionState } from "react";
import { runAccessAudit, type AuditState } from "../actions";

const GRADE_STYLE: Record<string, string> = {
  pass: "bg-emerald-600 text-white",
  warn: "bg-amber-600 text-white",
  fail: "bg-red-600 text-white",
};

export function AccessAuditPanel({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<AuditState, FormData>(
    runAccessAudit.bind(null, slug),
    null,
  );

  return (
    <div className="flex flex-col gap-4">
      <form action={action}>
        <button
          disabled={pending}
          className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {pending ? "Probing…" : "Run access audit"}
        </button>
      </form>

      {state && !state.ok && <p className="text-sm text-[var(--neg)]">{state.message}</p>}

      {state?.domains?.map((d) => {
        const blocked = d.agents.filter((a) => !a.allowed);
        return (
          <div key={d.domain} className="card-inset p-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className="font-mono text-sm">{d.domain}</span>
              <span
                className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${GRADE_STYLE[d.grade]}`}
              >
                {d.grade}
              </span>
            </div>
            {d.error && <p className="mb-2 text-xs text-[var(--neg)]">{d.error}</p>}
            <div className="mb-2 flex flex-wrap gap-2 text-xs">
              <span className="chip">
                robots.txt {d.robots_status === 200 ? "found" : (d.robots_status ?? "—")}
              </span>
              <span className="chip">
                {blocked.length === 0
                  ? "all AI crawlers allowed"
                  : `${blocked.length} crawler${blocked.length > 1 ? "s" : ""} blocked`}
              </span>
              <span className="chip">{d.has_json_ld ? "JSON-LD ✓" : "no JSON-LD"}</span>
              {d.rendering && (
                <span
                  className={`chip ${
                    d.rendering.verdict === "fail"
                      ? "text-[var(--neg)]"
                      : d.rendering.verdict === "warn"
                        ? "text-[var(--warn-t)]"
                        : "text-[var(--pos)]"
                  }`}
                  title={d.rendering.reason}
                >
                  {d.rendering.verdict === "pass"
                    ? "AI-readable HTML ✓"
                    : d.rendering.verdict === "warn"
                      ? "thin raw HTML"
                      : "JS-only (crawlers see blank)"}
                </span>
              )}
              <span className="chip">{d.has_llms_txt ? "llms.txt ✓" : "no llms.txt (optional)"}</span>
              {d.ua_blocked && (
                <span className="chip text-[var(--neg)]">bot UA rejected</span>
              )}
            </div>
            {d.issues.length > 0 ? (
              <ul className="space-y-1.5 text-xs text-[var(--text-2)]">
                {d.issues.map((issue, i) => (
                  <li key={i} className="flex gap-2">
                    <span aria-hidden className="text-[var(--text-3)]">→</span>
                    {issue}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-[var(--pos)]">
                Clean — every AI crawler can read this domain, and best practices are in place.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
