"use client";

import { useActionState } from "react";
import { importCaptures, type ActionState } from "../actions";

export function ImportCapturesForm({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    importCaptures.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-col gap-2">
      <p className="text-xs text-[var(--text-2)]">
        Answers a capture vendor collected (for example signed-in ChatGPT), as JSON:{" "}
        <code>{"{source, captures: [{surface, query, answer_html | answer, citations, captured_at, logged_in}]}"}</code>.
        Each import becomes a run and is measured like our own. Re-sending the same file skips
        duplicates.
      </p>
      <div className="flex gap-2">
        <input
          type="file"
          name="file"
          accept="application/json,.json"
          className="field min-w-0 flex-1 px-2 py-1.5 text-[12px]"
        />
        <button type="submit" disabled={pending} className="btn btn-primary px-3 py-1.5 text-[12px]">
          {pending ? "Importing…" : "Import"}
        </button>
      </div>
      {state && (
        <p className={`text-sm ${state.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
