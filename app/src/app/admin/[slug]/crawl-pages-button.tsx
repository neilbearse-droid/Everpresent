"use client";

import { useActionState } from "react";
import { crawlPowerPages, type ActionState } from "../actions";

export function CrawlPagesButton({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    crawlPowerPages.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex items-center gap-3">
      <button
        disabled={pending}
        className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-2)] disabled:opacity-50"
      >
        {pending ? "Queuing…" : "Crawl power pages now"}
      </button>
      {state && (
        <span className={`text-sm ${state.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </span>
      )}
    </form>
  );
}
