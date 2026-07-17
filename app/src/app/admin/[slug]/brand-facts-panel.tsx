"use client";

import { useActionState } from "react";
import { addBrandFact, deleteBrandFact, type ActionState } from "../actions";

export type BrandFact = {
  id: number;
  category: string;
  label: string;
  subject: string;
  aliases: string[];
  kind: string;
  expected: string;
};

function DeleteFact({ slug, id }: { slug: string; id: number }) {
  const [, action, pending] = useActionState<ActionState, FormData>(
    deleteBrandFact.bind(null, slug, id),
    null,
  );
  return (
    <form action={action}>
      <button
        disabled={pending}
        className="text-xs text-[var(--text-3)] underline-offset-2 hover:text-[var(--neg)] hover:underline disabled:opacity-50"
      >
        remove
      </button>
    </form>
  );
}

export function BrandFactsPanel({ slug, facts }: { slug: string; facts: BrandFact[] }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    addBrandFact.bind(null, slug),
    null,
  );

  return (
    <div className="flex flex-col gap-4">
      {facts.length > 0 && (
        <ul className="space-y-1.5">
          {facts.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-3 text-sm">
              <div className="min-w-0">
                <span className="chip mr-2 text-[10px]">{f.category}</span>
                <span className="font-medium text-[var(--text)]">{f.label}</span>
                <span className="ml-2 text-xs text-[var(--text-3)]">
                  {f.kind === "disallowed" ? "must never say" : "correct value"}:{" "}
                  <span className="font-mono">{f.expected}</span>
                </span>
              </div>
              <DeleteFact slug={slug} id={f.id} />
            </li>
          ))}
        </ul>
      )}

      <form action={action} className="grid gap-2 sm:grid-cols-2">
        <input name="label" placeholder="Label (e.g. Full-time MBA tuition)" className="field px-2.5 py-1.5 text-sm" />
        <input name="category" placeholder="Category (pricing, accreditation…)" className="field px-2.5 py-1.5 text-sm" />
        <input name="subject" placeholder="Subject term to detect (e.g. tuition)" className="field px-2.5 py-1.5 text-sm" />
        <input name="aliases" placeholder="Aliases, comma-separated (optional)" className="field px-2.5 py-1.5 text-sm" />
        <select name="kind" className="field px-2.5 py-1.5 text-sm" defaultValue="numeric">
          <option value="numeric">numeric — correct value</option>
          <option value="disallowed">disallowed — forbidden phrase</option>
        </select>
        <input name="expected" placeholder="Correct value / forbidden phrase" className="field px-2.5 py-1.5 text-sm" />
        <div className="sm:col-span-2">
          <button
            disabled={pending}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {pending ? "Adding…" : "Add fact"}
          </button>
          {state && (
            <span className={`ml-3 text-xs ${state.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
              {state.message}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
