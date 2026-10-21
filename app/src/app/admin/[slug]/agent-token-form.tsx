"use client";

import { useActionState } from "react";
import { rotateAgentLogToken, type ActionState } from "../actions";

export function AgentTokenForm({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    rotateAgentLogToken.bind(null, slug),
    null,
  );
  return (
    <form action={action} className="flex flex-col gap-2">
      <p className="text-xs text-[var(--text-2)]">
        Lets a log service (Cloudflare Logpush, Vercel, or the host&apos;s own pipeline) send the
        site&apos;s access logs to the AI Agents page. Only requests from AI bots are kept.
      </p>
      <button type="submit" disabled={pending} className="btn btn-ghost w-fit px-3 py-1.5 text-[12px]">
        {pending ? "Creating…" : "Create a new log token"}
      </button>
      {state && (
        <p className={`break-all font-mono text-xs ${state.ok ? "text-[var(--text)]" : "text-[var(--neg)]"}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
