"use client";

import { useActionState } from "react";
import { linkClerkOrg, type ActionState } from "../actions";

export function ClerkOrgForm({ slug, orgId }: { slug: string; orgId: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    linkClerkOrg.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="flex gap-2">
        <input
          name="clerk_org_id"
          defaultValue={orgId}
          placeholder="org_…"
          className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
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
