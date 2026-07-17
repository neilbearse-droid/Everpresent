"use client";

import { useActionState } from "react";
import { markShipped, unship, type ShipState } from "./actions";

export function MarkShipped({
  queryText,
  intervention,
}: {
  queryText: string;
  intervention: { id: number; shipped_at: string; url: string } | null;
}) {
  const [shipSt, shipAction, shipping] = useActionState<ShipState, FormData>(
    markShipped.bind(null, queryText),
    null,
  );
  const [unshipSt, unshipAction, unshipping] = useActionState<ShipState, FormData>(
    unship.bind(null, intervention?.id ?? 0),
    null,
  );

  if (intervention) {
    return (
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3 text-xs">
        <span className="chip text-[var(--pos)]">✓ shipped {intervention.shipped_at}</span>
        {intervention.url && (
          <a
            href={intervention.url}
            target="_blank"
            rel="noreferrer"
            className="text-[var(--accent)] hover:underline"
          >
            view the fix ↗
          </a>
        )}
        <span className="text-[var(--text-3)]">
          Lift appears under Proof as post-ship runs land.
        </span>
        <form action={unshipAction}>
          <button
            disabled={unshipping}
            className="text-[var(--text-3)] underline-offset-2 hover:text-[var(--neg)] hover:underline disabled:opacity-50"
          >
            undo
          </button>
        </form>
        {unshipSt && !unshipSt.ok && (
          <span className="text-[var(--neg)]">{unshipSt.message}</span>
        )}
      </div>
    );
  }

  return (
    <form
      action={shipAction}
      className="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3"
    >
      <input
        name="url"
        placeholder="URL of the published fix (optional)"
        className="w-72 max-w-full rounded-md border border-[var(--border)] bg-[var(--inset)] px-2.5 py-1.5 text-xs"
      />
      <button
        disabled={shipping}
        className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
      >
        {shipping ? "Recording…" : "Mark shipped"}
      </button>
      {shipSt && (
        <span className={`text-xs ${shipSt.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>
          {shipSt.message}
        </span>
      )}
    </form>
  );
}
