"use client";

import { useActionState } from "react";
import type { WaitlistSignup } from "@/lib/api";
import type { ActionState } from "../actions";
import { updateSignup } from "./actions";

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  contacted: "Contacted",
  invited: "Invited",
  activated: "Activated",
  declined: "Declined",
};

export function SignupRow({
  signup,
  statuses,
}: {
  signup: WaitlistSignup;
  statuses: string[];
}) {
  const action = updateSignup.bind(null, signup.id);
  const [state, formAction, pending] = useActionState<ActionState, FormData>(action, null);
  const campaign = Object.entries(signup.utm ?? {})
    .map(([key, value]) => `${key}=${value}`)
    .join(" · ");

  return (
    <tr className="align-top">
      <td className="whitespace-nowrap text-[var(--text-3)]">
        {new Date(signup.created_at).toLocaleDateString()}
      </td>
      <td>
        <div className="font-medium">{signup.name}</div>
        <a href={`mailto:${signup.email}`} className="bp-link text-[12.5px]">
          {signup.email}
        </a>
        {signup.submissions > 1 && (
          <span className="chip ml-2">{signup.submissions} submissions</span>
        )}
      </td>
      <td>
        <div>{signup.company || "—"}</div>
        <div className="text-[12.5px] text-[var(--text-3)]">{signup.title || "—"}</div>
      </td>
      <td className="text-[var(--text-2)]">{signup.industry || "—"}</td>
      <td className="text-[12.5px] text-[var(--text-3)]">
        {signup.source || "—"}
        {campaign && <div>{campaign}</div>}
      </td>
      <td>
        <form action={formAction} className="flex flex-wrap items-center gap-2">
          <select
            name="status"
            defaultValue={signup.status}
            className="field px-2 py-1 text-[12.5px]"
          >
            {statuses.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABEL[status] ?? status}
              </option>
            ))}
          </select>
          <input
            name="note"
            defaultValue={signup.note}
            placeholder="Note"
            className="field w-44 px-2 py-1 text-[12.5px]"
          />
          <button type="submit" disabled={pending} className="btn btn-ghost px-2.5 py-1">
            {pending ? "Saving…" : "Save"}
          </button>
          {state && !state.ok && (
            <span className="text-[12px] text-[var(--neg)]">{state.message}</span>
          )}
        </form>
      </td>
    </tr>
  );
}
