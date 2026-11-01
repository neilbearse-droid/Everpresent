"use client";

import { useActionState } from "react";
import { setEngineWeights, type ActionState } from "../actions";

export type EngineWeightDefaults = {
  defaults: Record<string, number>;
  labels: Record<string, string>;
  source: string;
  date: string;
};

/** Audience weights behind the pooled headline. Per-engine rates never
 * change; only how they are combined. 0 = measured, shown, not pooled. */
export function EngineWeightsForm({
  slug,
  defaults,
  current,
  changedOn,
}: {
  slug: string;
  defaults: EngineWeightDefaults;
  current: Record<string, number> | null;
  changedOn: string | null;
}) {
  const families = Object.keys(defaults.defaults);
  const [state, action, pending] = useActionState<ActionState, FormData>(
    setEngineWeights.bind(null, slug, families),
    null,
  );
  const custom = current !== null && Object.keys(current).length > 0;
  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        {families.map((f) => (
          <label key={f} className="flex items-center justify-between gap-2 text-xs">
            <span className="text-[var(--text-2)]">{defaults.labels[f] ?? f}</span>
            <input
              name={`w_${f}`}
              type="number"
              min={0}
              max={100}
              step={1}
              defaultValue={current?.[f] ?? defaults.defaults[f]}
              className="w-16 rounded-md border border-[var(--border)] bg-[var(--inset)] px-2 py-1 text-right text-sm tabular-nums"
            />
          </label>
        ))}
      </div>
      <p className="text-xs text-[var(--text-3)]">
        {custom
          ? `Custom weights since ${changedOn ?? "an earlier date"}; the default table is from ${defaults.date}.`
          : `Default table (${defaults.date}): ${defaults.source}.`}
      </p>
      <div className="flex items-center gap-2">
        <button
          disabled={pending}
          className="rounded-md bg-[var(--ink)] px-3 py-2 text-sm font-medium text-[var(--ink-text)] hover:bg-[var(--ink-hover)] disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save weights"}
        </button>
        {custom && (
          <button
            name="reset"
            value="1"
            disabled={pending}
            className="btn px-3 text-[12.5px] disabled:opacity-50"
          >
            Reset to default
          </button>
        )}
      </div>
      {state && (
        <p className={`text-sm ${state.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
