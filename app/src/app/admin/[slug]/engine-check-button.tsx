"use client";

import { useActionState } from "react";
import { runEngineCheck, type ActionState } from "../actions";

/** One cheap live call per enabled engine: proves keys, browser captures and
 * parsing before a full run. */
export function EngineCheckButton({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    runEngineCheck.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-wrap items-center gap-3 px-4 py-3">
      <button disabled={pending} className="btn btn-primary px-3 py-1.5 text-[12.5px] disabled:opacity-50">
        {pending ? "Queuing…" : "Test every engine"}
      </button>
      <span className="text-xs text-[var(--text-3)]">
        One short live call per engine, a few cents in total. Run it after any deploy or key change.
      </span>
      {state && (
        <span className={`text-sm ${state.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </span>
      )}
    </form>
  );
}
