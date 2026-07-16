import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type RawEnvelope } from "@/lib/api";
import { surfaceLabel } from "@/lib/viz";

function AnswerColumn({ title, envelope }: { title: string; envelope: RawEnvelope }) {
  return (
    <section className="min-w-0 card p-5">
      <h2 className="mb-1 text-sm font-medium text-slate-200">{title}</h2>
      <p className="mb-4 text-xs text-slate-500">
        {surfaceLabel(envelope.surface)} · {envelope.model} · persona: {envelope.persona}
      </p>
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{envelope.parsed_text}</p>
    </section>
  );
}

/** The dual-fidelity view (§1): the same query answered through the provider
 * API and through the real consumer web interface, side by side. */
export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ a?: string; b?: string }>;
}) {
  const { a, b } = await searchParams;
  if (!a || !b) notFound();
  const [modeA, modeB] = await Promise.all([
    apiFetch<RawEnvelope>(`/api/tenant/results/${a}/raw`),
    apiFetch<RawEnvelope>(`/api/tenant/results/${b}/raw`),
  ]);
  if (!modeA.data || !modeB.data) notFound();

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <Link href="/dashboard/queries" className="text-sm text-indigo-400 hover:underline">
        ← Queries
      </Link>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">API vs web interface</h1>
      <p className="mt-1 mb-6 text-sm text-slate-400">“{modeA.data.query}”</p>
      <div className="grid gap-6 lg:grid-cols-2">
        <AnswerColumn title="Mode A — provider API" envelope={modeA.data} />
        <AnswerColumn title="Mode B — consumer web interface" envelope={modeB.data} />
      </div>
    </main>
  );
}
