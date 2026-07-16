"use client";

import { useActionState } from "react";
import { createTenant, type ActionState } from "./actions";

export function CreateTenantForm() {
  const [state, action, pending] = useActionState<ActionState, FormData>(createTenant, null);
  return (
    <form action={action} className="flex flex-col gap-3">
      <input
        name="name"
        placeholder="Name (e.g. Smith School of Business)"
        required
        className="rounded-md border border-[var(--border)] bg-[var(--inset)] px-3 py-2 text-sm"
      />
      <input
        name="slug"
        placeholder="slug (e.g. smith)"
        required
        pattern="[a-z0-9-]+"
        className="rounded-md border border-[var(--border)] bg-[var(--inset)] px-3 py-2 text-sm"
      />
      <button
        type="submit"
        disabled={pending}
        className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
      >
        {pending ? "Creating…" : "Create tenant"}
      </button>
      {state && !state.ok && <p className="text-sm text-red-400">{state.message}</p>}
    </form>
  );
}
