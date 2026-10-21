import type { RawEnvelope } from "@/lib/api";
import { surfaceLabel } from "@/lib/viz";

/** `showCost`: admin only. Answer cost is internal (it reveals the margin). */
export function RawResponseView({
  envelope,
  showCost = false,
}: {
  envelope: RawEnvelope;
  showCost?: boolean;
}) {
  return (
    <div className="space-y-6">
      <section className="card p-5">
        <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">Question</h2>
        <p>{envelope.query}</p>
        <h2 className="mt-4 mb-1 text-sm font-medium text-[var(--text-2)]">
          Persona: {envelope.persona}
        </h2>
        <p className="whitespace-pre-wrap text-sm text-[var(--text-2)]">{envelope.persona_prompt}</p>
        <p className="mt-4 text-xs text-[var(--text-3)]">
          {surfaceLabel(envelope.surface)}
          {envelope.mode === "import" ? " · imported" : ""} · {envelope.model}
          {showCost && ` · $${envelope.cost_usd.toFixed(5)}`}
        </p>
      </section>

      <section className="card p-5">
        <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">Answer</h2>
        <p className="whitespace-pre-wrap leading-relaxed">{envelope.parsed_text}</p>
      </section>

      <details className="card p-5">
        <summary className="cursor-pointer text-sm font-medium text-[var(--text-2)]">
          Full response from the engine (JSON)
        </summary>
        <pre className="mt-3 overflow-x-auto text-xs text-[var(--text-2)]">
          {JSON.stringify(envelope.response, null, 2)}
        </pre>
      </details>
    </div>
  );
}
