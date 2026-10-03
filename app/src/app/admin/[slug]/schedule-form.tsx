"use client";

import { useActionState } from "react";
import { putSchedule, type ActionState } from "../actions";

export function ScheduleForm({
  slug,
  cronExpr,
  enabled,
}: {
  slug: string;
  cronExpr: string;
  enabled: boolean;
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    putSchedule.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-[220px] flex-1 flex-col text-xs text-[var(--text-2)]">
          Cron expression (UTC). Recommended: <code>0 13 * * 1,3,5</code> = Mon/Wed/Fri
          13:00. Three runs a week with repeat samples measures better than a daily single
          reading, at lower cost.
          <input
            name="cron_expr"
            defaultValue={cronExpr || "0 13 * * 1,3,5"}
            placeholder="0 13 * * 1,3,5"
            required
            className="mt-1 rounded-md border border-[var(--border)] bg-[var(--inset)] px-3 py-2 font-mono text-sm text-[var(--text)]"
          />
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-[var(--text-2)]">
          <input type="checkbox" name="enabled" defaultChecked={enabled} />
          enabled
        </label>
        <button
          disabled={pending}
          className="rounded-md bg-[var(--ink)] px-3 py-2 text-sm font-medium text-[var(--ink-text)] hover:bg-[var(--ink-hover)] disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save"}
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
