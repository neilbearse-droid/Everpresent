"use client";

import { useActionState } from "react";
import { triggerRun, type ActionState } from "../../actions";

export function TriggerRunButton({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState>(
    triggerRun.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-col items-end gap-2">
      <button
        type="submit"
        disabled={pending}
        className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
      >
        {pending ? "Triggering…" : "Trigger run"}
      </button>
      {state && (
        <p className={`text-sm ${state.ok ? "text-[var(--pos)]" : "text-[var(--warn-t)]"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
