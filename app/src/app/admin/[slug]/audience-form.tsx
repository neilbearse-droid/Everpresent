"use client";

import { useActionState } from "react";
import type { AudienceCatalog } from "@/lib/api";
import { surfaceLabel } from "@/lib/viz";
import { setAudience, type ActionState } from "../actions";

export function AudienceForm({
  slug,
  current,
  catalog,
}: {
  slug: string;
  current: string;
  catalog: AudienceCatalog;
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    setAudience.bind(null, slug),
    null,
  );
  const stale = catalog.pins.filter((p) => p.stale);
  const oldest = catalog.pins.reduce((a, b) => (a.age_days >= b.age_days ? a : b), catalog.pins[0]);

  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {catalog.choices.map((choice) => {
          const on = choice.key === current;
          return (
            <label
              key={choice.key}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors ${
                on
                  ? "border-[var(--ink)] bg-[var(--surface-2)] ring-1 ring-[var(--ink)]"
                  : "border-[var(--border)] hover:border-[var(--border-strong)]"
              }`}
            >
              <input
                type="radio"
                name="audience"
                value={choice.key}
                defaultChecked={on}
                className="mt-0.5 accent-[var(--ink)]"
              />
              <span className="flex-1">
                <span className="font-medium">{choice.label}</span>
                <span className="ml-2 text-xs uppercase tracking-wide text-[var(--text-2)]">
                  {choice.key}
                </span>
                <span className="mt-1 block text-xs text-[var(--text-2)]">
                  Each engine answers as its {choice.tier} tier does today:
                </span>
                <span className="mt-1 grid gap-0.5 text-xs tabular-nums">
                  {Object.entries(choice.models).map(([surface, model]) => (
                    <span key={surface} className="flex justify-between gap-3">
                      <span className="text-[var(--text-2)]">{surfaceLabel(surface)}</span>
                      <span className="font-mono">{model}</span>
                    </span>
                  ))}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      {oldest && (
        <p className={`text-xs ${stale.length ? "text-[var(--warn-t)]" : "text-[var(--text-2)]"}`}>
          {stale.length
            ? `Out of date: ${stale.map((p) => surfaceLabel(p.surface)).join(", ")} last checked over ${catalog.stale_after_days} days ago. Re-check what each app serves and re-pin.`
            : `Models last checked ${oldest.as_of} (${oldest.age_days} days ago); flagged after ${catalog.stale_after_days}.`}
        </p>
      )}
      <div className="flex items-center gap-3">
        <button
          disabled={pending}
          className="rounded-md bg-[var(--ink)] px-3 py-2 text-sm font-medium text-[var(--ink-text)] hover:bg-[var(--ink-hover)] disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save audience"}
        </button>
        {state && (
          <span className={`text-sm ${state.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
            {state.message}
          </span>
        )}
      </div>
    </form>
  );
}
