"use client";

import { useActionState } from "react";
import { buildDemoClient, type ActionState } from "./actions";

export function DemoClientForm() {
  const [state, action, pending] = useActionState<ActionState, FormData>(buildDemoClient, null);
  return (
    <form action={action} className="flex flex-col gap-3">
      <p className="text-sm text-[var(--text-2)]">
        A fictional brand, Northpeak (northpeak.example), with four made-up rivals and a month of
        answers, bot logs, page checks and one logged fix. Every dashboard and play is produced by
        the real processing, so the action steps match the data. Rebuilding replaces the demo&apos;s
        data. Paid runs are disabled for it.
      </p>
      <label className="text-xs text-[var(--text-2)]">
        Clerk organization ID to view it as (optional; you can link it later)
      </label>
      <input name="clerk_org_id" placeholder="org_…" className="field px-2 py-1.5 text-[13px]" />
      <button type="submit" disabled={pending} className="btn btn-primary self-start px-3 py-1.5 text-[13px]">
        {pending ? "Queuing…" : "Build demo client"}
      </button>
      {state && (
        <p className={`text-sm ${state.ok ? "text-[var(--text-2)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
