"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef, useState } from "react";
import { runEngineCheck, type ActionState } from "../actions";

const POLL_MS = 4000;
const GIVE_UP_MS = 6 * 60 * 1000; // browser captures can take a few minutes

/** One cheap live call per enabled engine: proves keys, browser captures and
 * parsing before a full run. After queuing, the table refreshes itself until
 * every switched-on engine has a result newer than the click. */
export function EngineCheckButton({
  slug,
  engines,
}: {
  slug: string;
  /** Switched-on engines and when each was last checked. */
  engines: { code: string; at: string | null }[];
}) {
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionState, FormData>(
    runEngineCheck.bind(null, slug),
    null,
  );
  const [since, setSince] = useState<number | null>(null);
  const handled = useRef<ActionState>(null);

  // A successful queue starts the watch (once per submission).
  useEffect(() => {
    if (state && state !== handled.current) {
      handled.current = state;
      if (state.ok) setSince(Date.now());
    }
  }, [state]);

  const done = since
    ? engines.filter((e) => e.at && new Date(e.at).getTime() >= since - 5000).length
    : 0;
  const watching = since !== null && done < engines.length && Date.now() - since < GIVE_UP_MS;

  useEffect(() => {
    if (!watching) return;
    const t = setInterval(() => router.refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [watching, router]);

  const status =
    since === null
      ? null
      : done >= engines.length
        ? `All ${engines.length} engines checked. Results are in the table below.`
        : watching
          ? `Checking… ${done} of ${engines.length} engines done. This table updates by itself.`
          : `${done} of ${engines.length} engines reported back. The rest are still running or stuck; refresh in a minute.`;

  return (
    <form action={action} className="flex flex-wrap items-center gap-3 px-4 py-3">
      <button
        disabled={pending || watching}
        className="btn btn-primary px-3 py-1.5 text-[12.5px] disabled:opacity-50"
      >
        {pending ? "Queuing…" : watching ? "Checking…" : "Test every engine"}
      </button>
      <span className="text-xs text-[var(--text-3)]">
        One short live call per engine, a few cents in total. Run it after any deploy or key change.
      </span>
      {state && !state.ok && <span className="text-sm text-[var(--neg)]">{state.message}</span>}
      {status && (
        <span className="text-sm text-[var(--text-2)]" role="status" aria-live="polite">
          {watching && (
            <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--accent)] align-middle" />
          )}
          {status}
        </span>
      )}
    </form>
  );
}
