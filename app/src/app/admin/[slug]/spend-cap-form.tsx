"use client";

import { useActionState } from "react";
import { setSpendCap, type ActionState } from "../actions";

export function SpendCapForm({ slug, cap }: { slug: string; cap: number }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    setSpendCap.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="mt-4 flex flex-col gap-2">
      <div className="flex items-end gap-2">
        <label className="flex flex-col text-xs text-slate-400">
          Monthly spend cap (USD)
          <input
            name="monthly_spend_cap_usd"
            type="number"
            min="0"
            step="0.01"
            defaultValue={cap}
            className="mt-1 w-32 rounded-md border border-[var(--border)] bg-[var(--inset)] px-3 py-2 text-sm text-slate-100"
          />
        </label>
        <button
          disabled={pending}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save cap"}
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
