"use client";

import { useActionState, useEffect, useState } from "react";
import {
  draftConfig,
  importSeed,
  importYaml,
  type ActionState,
  type DraftConfigState,
} from "../actions";

export type BundledSeed = { name: string; brand: string; queries: number; personas: number };

export function ImportYamlForm({ slug, seeds = [] }: { slug: string; seeds?: BundledSeed[] }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    importYaml.bind(null, slug),
    null,
  );
  const [seedState, seedAction, seedPending] = useActionState<ActionState, FormData>(
    importSeed.bind(null, slug),
    null,
  );
  const [draftState, draftAction, draftPending] = useActionState<DraftConfigState, FormData>(
    draftConfig.bind(null, slug),
    null,
  );
  const [yamlText, setYamlText] = useState("");
  useEffect(() => {
    if (draftState?.yaml) setYamlText(draftState.yaml);
  }, [draftState]);
  return (
    <div className="flex flex-col gap-5">
      <form action={draftAction} className="flex flex-col gap-2">
        <label className="text-xs text-[var(--text-2)]">
          New brand? Draft a config from its domain. Nothing is imported until you review it.
        </label>
        <div className="flex gap-2">
          <input
            name="domain"
            required
            placeholder="example.com"
            className="field min-w-0 flex-1 px-2 py-1.5 text-[12px]"
          />
          <button
            type="submit"
            disabled={draftPending}
            className="btn btn-primary px-3 py-1.5 text-[12px]"
          >
            {draftPending ? "Drafting…" : "Draft"}
          </button>
        </div>
        {draftState && (
          <p className={`text-sm ${draftState.ok ? "text-[var(--text-2)]" : "text-[var(--neg)]"}`}>
            {draftState.message}
          </p>
        )}
        {draftState?.warnings?.map((w) => (
          <p key={w} className="text-xs text-[var(--text-2)]">
            <span className="bp-neg mr-1.5">Check</span>
            {w}
          </p>
        ))}
      </form>
      {seeds.length > 0 && (
        <form action={seedAction} className="flex flex-col gap-2">
          <label className="text-xs text-[var(--text-2)]">
            Load a bundled config (no copy-paste). Replaces this tenant&apos;s brand,
            competitors, personas, questions and engines.
          </label>
          <div className="flex gap-2">
            <select name="seed" className="field min-w-0 flex-1 px-2 py-1.5 text-[12px]" defaultValue={seeds[0].name}>
              {seeds.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.brand} ({s.queries} questions, {s.personas} personas)
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={seedPending}
              className="btn btn-primary px-3 py-1.5 text-[12px]"
            >
              {seedPending ? "Loading…" : "Load"}
            </button>
          </div>
          {seedState && (
            <p className={`text-sm ${seedState.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
              {seedState.message}
            </p>
          )}
        </form>
      )}
      <form action={action} className="flex flex-col gap-3">
        <label className="text-xs text-[var(--text-2)]">Or paste a config</label>
        <textarea
          name="yaml"
          rows={draftState?.yaml ? 24 : 10}
          required
          value={yamlText}
          onChange={(e) => setYamlText(e.target.value)}
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
    </div>
  );
}
