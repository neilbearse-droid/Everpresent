"use client";

import { useActionState } from "react";
import { runAccessAudit, type AuditState } from "../actions";

const GRADE_STYLE: Record<string, string> = {
  pass: "border border-[var(--border)] bg-[var(--surface)] text-[var(--pos)]",
  warn: "border border-[var(--border)] bg-[var(--surface)] text-[var(--warn-t)]",
  fail: "border border-[var(--border)] bg-[var(--surface)] text-[var(--neg)]",
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
          className="rounded-md bg-[var(--ink)] px-3 py-2 text-sm font-medium text-[var(--ink-text)] hover:bg-[var(--ink-hover)] disabled:opacity-50"
        >
          {pending ? "Checking…" : "Run access audit"}
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
                className={`rounded px-2 py-0.5 text-xs font-semibold ${GRADE_STYLE[d.grade]}`}
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
              <span className="chip">{d.has_json_ld ? "has JSON-LD" : "no JSON-LD"}</span>
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
                    ? "readable without JavaScript"
                    : d.rendering.verdict === "warn"
                      ? "little text without JavaScript"
                      : "needs JavaScript (crawlers see a blank page)"}
                </span>
              )}
              <span className="chip">{d.has_llms_txt ? "has llms.txt" : "no llms.txt (optional)"}</span>
              {d.entity && (
                <span
                  className={`chip ${
                    d.entity.has_sameas || d.entity.links_wikipedia
                      ? "text-[var(--pos)]"
                      : "text-[var(--text-3)]"
                  }`}
                >
                  {d.entity.has_sameas || d.entity.links_wikipedia
                    ? "links to Wikipedia or profiles"
                    : "no Wikipedia or profile links"}
                </span>
              )}
              {d.ua_blocked && (
                <span className="chip text-[var(--neg)]">rejects AI bots by user agent</span>
              )}
            </div>
            {d.issues.length > 0 ? (
              <ul className="list-disc space-y-1.5 pl-4 text-xs text-[var(--text-2)]">
                {d.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-[var(--pos)]">
                No problems found. Every AI crawler can read this domain.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
