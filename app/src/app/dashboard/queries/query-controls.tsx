"use client";

import { useActionState } from "react";
import type { QueryControlsPayload } from "@/lib/api";
import { setQueryActive, setQueryPersonas, type ControlState } from "./actions";

/** Pause / resume one question. */
export function ActiveToggle({ id, active }: { id: number; active: boolean }) {
  const [state, action, pending] = useActionState<ControlState, FormData>(
    setQueryActive.bind(null, id, !active),
    null,
  );
  return (
    <form action={action} className="inline-flex flex-col items-start gap-1">
      <button
        disabled={pending}
        title={
          active
            ? "Pause: leaves the next run and the rates from today; history stays."
            : "Resume: back in the next run."
        }
        className="btn px-2 py-1 text-[12px] disabled:opacity-50"
      >
        {pending ? "…" : active ? "Pause" : "Resume"}
      </button>
      {state && state.message && (
        <span className={`text-xs ${state.ok ? "text-[var(--text-3)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </span>
      )}
    </form>
  );
}

/** Which personas a question runs against, besides the baseline. Personas
 * outside the plan are shown but locked, with the plan that unlocks them. */
export function PersonaPicker({
  id,
  chosen,
  controls,
}: {
  id: number;
  chosen: string[];
  controls: QueryControlsPayload;
}) {
  const segments = controls.personas.map((p) => p.segment);
  const [state, action, pending] = useActionState<ControlState, FormData>(
    setQueryPersonas.bind(null, id, segments),
    null,
  );
  if (!controls.selective || controls.personas.length === 0) {
    return <span className="text-xs text-[var(--text-3)]">—</span>;
  }
  return (
    <form action={action} className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {controls.personas.map((p) => (
          <label
            key={p.segment}
            className={`inline-flex items-center gap-1 text-xs ${
              p.in_plan ? "" : "text-[var(--text-3)]"
            }`}
            title={
              p.in_plan
                ? ""
                : `Available on the ${controls.unlock_plan ?? "next"} plan`
            }
          >
            <input
              type="checkbox"
              name={`p_${p.segment}`}
              defaultChecked={chosen.includes(p.segment)}
              disabled={!p.in_plan || pending}
            />
            {p.name}
            {!p.in_plan && <span className="chip">{controls.unlock_plan ?? "upgrade"}</span>}
          </label>
        ))}
        <button disabled={pending} className="btn px-2 py-0.5 text-[11px] disabled:opacity-50">
          {pending ? "…" : "Save"}
        </button>
      </div>
      {state && state.message && (
        <span className={`text-xs ${state.ok ? "text-[var(--text-3)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </span>
      )}
    </form>
  );
}
