import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Me, type RawEnvelope, type TenantSummary } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { PageLead } from "@/components/page-lead";
import { surfaceLabel } from "@/lib/viz";

function AnswerColumn({ title, envelope }: { title: string; envelope: RawEnvelope }) {
  return (
    <section className="min-w-0 card p-4">
      <h2 className="mb-1 text-sm font-medium text-[var(--text)]">{title}</h2>
      <p className="mb-4 text-xs text-[var(--text-3)]">
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
  const [modeA, modeB, me, tenant] = await Promise.all([
    apiFetch<RawEnvelope>(`/api/tenant/results/${a}/raw`),
    apiFetch<RawEnvelope>(`/api/tenant/results/${b}/raw`),
    apiFetch<Me>("/api/me"),
    apiFetch<TenantSummary>("/api/tenant"),
  ]);
  if (!modeA.data || !modeB.data) notFound();

  // The lead: do the two answers agree about you? A plain name match on the
  // answer text; the measured classification lives on the Queries page.
  const brand = tenant.data?.brand_name ?? tenant.data?.name ?? "";
  const names = (text: string) => brand !== "" && text.toLowerCase().includes(brand.toLowerCase());
  const inApi = names(modeA.data.parsed_text);
  const inWeb = names(modeB.data.parsed_text);
  const lead =
    inApi && inWeb
      ? { tells: `Both answers name ${brand}.`, act: "Read the website one; that's what buyers see.", tone: "good" as const }
      : !inApi && !inWeb
        ? { tells: `Neither answer names ${brand}.`, act: "Close this gap; Engines says which kind it is.", href: "/dashboard/engines", hrefLabel: "Engines", tone: "bad" as const }
        : inWeb
          ? { tells: `The website names ${brand}; the API doesn't.`, act: "Nothing urgent; buyers see the website.", tone: "neutral" as const }
          : { tells: `The API names ${brand}; the website doesn't.`, act: "Beat the rival and sources the website answer uses.", href: "/dashboard/citations", hrefLabel: "Citations", tone: "bad" as const };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Queries" isSuperadmin={me.data?.is_superadmin} />
      <Link href="/dashboard/queries" className="text-sm text-[var(--accent)] hover:underline">
        ← Queries
      </Link>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">API answer vs website answer</h1>
      <p className="mt-1 mb-6 text-sm text-[var(--text-2)]">“{modeA.data.query}”</p>
      <PageLead {...lead} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <AnswerColumn title="Developer API" envelope={modeA.data} />
        <AnswerColumn title="Public website" envelope={modeB.data} />
      </div>
    </main>
  );
}
