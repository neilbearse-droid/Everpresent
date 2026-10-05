"use client";

import { useActionState } from "react";
import { reprocessTenant, type ActionState } from "../actions";

/** Re-read every stored run with the current detectors and parsers. */
export function ReprocessButton({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    reprocessTenant.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-wrap items-center gap-3">
      <button disabled={pending} className="btn btn-ghost px-3 py-1.5 text-[12.5px] disabled:opacity-50">
        {pending ? "Queuing…" : "Reprocess history"}
      </button>
      {state && (
        <span className={`text-sm ${state.ok ? "text-[var(--text-2)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </span>
      )}
    </form>
  );
}
