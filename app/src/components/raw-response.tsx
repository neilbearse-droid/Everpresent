import type { RawEnvelope } from "@/lib/api";

export function RawResponseView({ envelope }: { envelope: RawEnvelope }) {
  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-slate-700 bg-slate-900 p-5">
        <h2 className="mb-1 text-sm font-medium text-slate-400">Query</h2>
        <p>{envelope.query}</p>
        <h2 className="mt-4 mb-1 text-sm font-medium text-slate-400">
          Persona — {envelope.persona}
        </h2>
        <p className="whitespace-pre-wrap text-sm text-slate-300">{envelope.persona_prompt}</p>
        <p className="mt-4 text-xs text-slate-500">
          {envelope.surface} · mode {envelope.mode} · {envelope.model} · $
          {envelope.cost_usd.toFixed(5)}
        </p>
      </section>

      <section className="rounded-lg border border-slate-700 bg-slate-900 p-5">
        <h2 className="mb-3 text-sm font-medium text-slate-400">Response</h2>
        <p className="whitespace-pre-wrap leading-relaxed">{envelope.parsed_text}</p>
      </section>

      <details className="rounded-lg border border-slate-700 bg-slate-900 p-5">
        <summary className="cursor-pointer text-sm font-medium text-slate-400">
          Raw provider payload (JSON)
        </summary>
        <pre className="mt-3 overflow-x-auto text-xs text-slate-300">
          {JSON.stringify(envelope.response, null, 2)}
        </pre>
      </details>
    </div>
  );
}
