import type { RawEnvelope } from "@/lib/api";

export function RawResponseView({ envelope }: { envelope: RawEnvelope }) {
  return (
    <div className="space-y-6">
      <section className="card p-5">
        <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">Query</h2>
        <p>{envelope.query}</p>
        <h2 className="mt-4 mb-1 text-sm font-medium text-[var(--text-2)]">
          Persona — {envelope.persona}
        </h2>
        <p className="whitespace-pre-wrap text-sm text-[var(--text-2)]">{envelope.persona_prompt}</p>
        <p className="mt-4 text-xs text-[var(--text-3)]">
          {envelope.surface} · mode {envelope.mode} · {envelope.model} · $
          {envelope.cost_usd.toFixed(5)}
        </p>
      </section>

      <section className="card p-5">
        <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">Response</h2>
        <p className="whitespace-pre-wrap leading-relaxed">{envelope.parsed_text}</p>
      </section>

      <details className="card p-5">
        <summary className="cursor-pointer text-sm font-medium text-[var(--text-2)]">
          Raw provider payload (JSON)
        </summary>
        <pre className="mt-3 overflow-x-auto text-xs text-[var(--text-2)]">
          {JSON.stringify(envelope.response, null, 2)}
        </pre>
      </details>
    </div>
  );
}
