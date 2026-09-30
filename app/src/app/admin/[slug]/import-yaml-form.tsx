"use client";

import { useActionState } from "react";
import { importYaml, type ActionState } from "../actions";

export function ImportYamlForm({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    importYaml.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-col gap-3">
      <textarea
        name="yaml"
        rows={10}
        required
        placeholder={"brand:\n  name: …\npersonas:\n  - name: …\nqueries:\n  - text: …"}
        className="rounded-md border border-[var(--border)] bg-[var(--inset)] px-3 py-2 font-mono text-xs"
      />
      <button
        type="submit"
        disabled={pending}
        className="self-start rounded-md bg-[var(--ink)] px-4 py-2 text-sm font-medium text-[var(--ink-text)] hover:bg-[var(--ink-hover)] disabled:opacity-50"
      >
        {pending ? "Importing…" : "Import"}
      </button>
      {state && (
        <p className={`text-sm ${state.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
