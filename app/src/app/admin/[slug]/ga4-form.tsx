"use client";

import { useActionState } from "react";
import { setGa4Property, type ActionState } from "../actions";

export function Ga4Form({ slug, propertyId }: { slug: string; propertyId: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    setGa4Property.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="flex gap-2">
        <input
          name="ga4_property_id"
          defaultValue={propertyId}
          placeholder="123456789"
          className="flex-1 rounded-md border border-[var(--border)] bg-[var(--inset)] px-3 py-2 text-sm"
        />
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
