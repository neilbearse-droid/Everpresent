"use client";

import { useActionState } from "react";
import type { PlanLimits } from "@/lib/api";
import { setPlan, type ActionState } from "../actions";

const ORDER = ["monitor", "diagnose", "command", "custom"];

function cap(v: number | null): string {
  return v === null ? "∞" : String(v);
}

export function PlanForm({
  slug,
  current,
  plans,
}: {
  slug: string;
  current: string;
  plans: Record<string, PlanLimits>;
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    setPlan.bind(null, slug),
    null,
  );
  const keys = ORDER.filter((k) => plans[k]);

  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="grid gap-2">
        {keys.map((key) => {
          const p = plans[key];
          const on = key === current;
          return (
            <label
              key={key}
              className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-sm transition-colors ${
                on
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "border-[var(--border)] hover:border-[var(--border-strong)]"
              }`}
            >
              <input
                type="radio"
                name="plan"
                value={key}
                defaultChecked={on}
                className="accent-[var(--accent)]"
              />
              <span className="flex-1">
                <span className="font-medium">{p.label}</span>
                <span className="ml-2 font-mono text-xs text-[var(--text-3)]">
                  {p.monthly_price_usd > 0 ? `$${p.monthly_price_usd}/mo` : "custom"}
                </span>
                <span className="mt-0.5 block font-mono text-xs text-[var(--text-3)]">
                  {cap(p.max_prompts)} prompts · {cap(p.max_personas)} personas ·{" "}
                  {cap(p.max_engines)} engines ·{" "}
                  {p.max_runs_per_day === null ? "∞" : `${p.max_runs_per_day}`}×/day ·{" "}
                  {p.diagnosis ? "diagnosis" : "no diagnosis"} · {p.model_tier}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      <div className="flex items-center gap-3">
        <button
          disabled={pending}
          className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save plan"}
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
