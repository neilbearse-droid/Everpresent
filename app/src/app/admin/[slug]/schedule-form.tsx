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
      <div className="flex items-end gap-2">
        <label className="flex flex-1 flex-col text-xs text-slate-400">
          Cron expression (UTC) — e.g. <code>0 13 * * 1</code> = Mondays 13:00
          <input
            name="cron_expr"
            defaultValue={cronExpr}
            placeholder="0 13 * * 1"
            required
            className="mt-1 rounded-md border border-[var(--border)] bg-[var(--inset)] px-3 py-2 font-mono text-sm text-slate-100"
          />
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-slate-300">
          <input type="checkbox" name="enabled" defaultChecked={enabled} />
          enabled
        </label>
        <button
          disabled={pending}
          className="rounded-md bg-indigo-500 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save"}
        </button>
      </div>
      {state && (
        <p className={`text-sm ${state.ok ? "text-emerald-400" : "text-red-400"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
