"use client";

import { useActionState } from "react";
import { resumeRun, type ActionState } from "../../actions";

/** Finish a failed run: the answers it already saved stay, and only the
 * missing cells are asked again. */
export function ResumeRunButton({ slug, runId }: { slug: string; runId: number }) {
  const [state, action, pending] = useActionState<ActionState>(
    resumeRun.bind(null, slug, runId),
    null,
  );
  return (
    <form action={action} className="flex flex-col items-start gap-1">
      <button
        type="submit"
        disabled={pending}
        title="Re-asks only the cells this run is missing; what it saved stays."
        className="btn px-2 py-1 text-[12px] disabled:opacity-50"
      >
        {pending ? "Queuing…" : "Resume"}
      </button>
      {state && (
        <span className={`text-xs ${state.ok ? "text-[var(--text-2)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </span>
      )}
    </form>
  );
}
