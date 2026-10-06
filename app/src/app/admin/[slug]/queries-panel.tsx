"use client";

import { useActionState } from "react";
import { addQueries, setQueryBranded, type ActionState } from "../actions";

export type AdminQuery = {
  id: number;
  text: string;
  corpus_tag: string;
  active: boolean;
  branded: boolean;
};

function BrandedToggle({ slug, query }: { slug: string; query: AdminQuery }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    setQueryBranded.bind(null, slug, query.id, !query.branded),
    null,
  );
  return (
    <form action={action} className="flex items-center gap-2">
      <button
        disabled={pending}
        title={
          query.branded
            ? "Branded — measured in the Brand layer, out of the visibility score. Click to make competitive."
            : "Competitive — counts toward the visibility score. Click to mark branded."
        }
        className={`rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] font-semibold disabled:opacity-50 ${
          query.branded
            ? "border-[var(--accent)] text-[var(--accent)]"
            : "border-[var(--border)] text-[var(--text-3)] hover:text-[var(--text-2)]"
        }`}
      >
        {pending ? "…" : query.branded ? "branded" : "competitive"}
      </button>
      {state && !state.ok && <span className="text-xs text-[var(--neg)]">{state.message}</span>}
    </form>
  );
}

function AddQueriesForm({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    addQueries.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="mb-5 space-y-2">
      <label className="block text-xs font-medium text-[var(--text-2)]" htmlFor="add-queries">
        Add questions, one per line
      </label>
      <textarea
        id="add-queries"
        name="text"
        rows={5}
        required
        placeholder={"Is Botnia Skincare good for sensitive skin?\nWhat is the best skincare for sensitive skin?"}
        className="w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--surface)] p-2 text-sm"
      />
      <div className="flex items-center gap-3">
        <button disabled={pending} className="btn btn-primary px-3 text-[12.5px] disabled:opacity-50">
          {pending ? "Adding…" : "Add questions"}
        </button>
        <span className="text-xs text-[var(--text-3)]">
          Questions naming the brand are filed as branded. Duplicates are skipped.
        </span>
      </div>
      {state && (
        <p className={`text-xs ${state.ok ? "text-[var(--text-2)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}

export function QueriesPanel({ slug, queries }: { slug: string; queries: AdminQuery[] }) {
  const branded = queries.filter((q) => q.branded).length;
  return (
    <section className="card p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="font-medium">Queries ({queries.length})</h2>
        <span className="text-xs text-[var(--text-3)]">
          {branded} branded · {queries.length - branded} competitive
        </span>
      </div>
      <p className="mb-3 text-xs text-[var(--text-3)]">
        Branded queries probe what the model says about the brand — measured in the Brand
        layer and excluded from the competitive visibility score. Toggle takes effect on the
        next processed run.
      </p>
      <AddQueriesForm slug={slug} />
      <ul className="space-y-2">
        {queries.map((q) => (
          <li key={q.id} className="flex items-center justify-between gap-3 text-sm">
            <span>
              {q.text}
              <span className="ml-2 text-xs text-[var(--text-3)]">{q.corpus_tag}</span>
              {!q.active && <span className="ml-2 text-xs text-[var(--text-3)]">(inactive)</span>}
            </span>
            <BrandedToggle slug={slug} query={q} />
          </li>
        ))}
      </ul>
    </section>
  );
}
