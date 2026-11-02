import Link from "next/link";
import { apiFetch, type Me, type Recommendation } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { StatusButtons } from "@/components/plan-buttons";
import { Linkify } from "@/components/ui";

const KIND_LABELS: Record<string, string> = {
  accuracy: "Wrong fact",
  crawler_access: "Bot access",
  broken_page: "Broken page",
  refresh: "Lost citation",
  subquery: "Sub-search",
  reviews: "Reviews",
  earned: "Earned media",
  owned: "Your site",
  own_page: "Your page",
  model_change: "Model change",
  community: "Community",
  reference: "Reference",
  web_search: "Search gap",
  aio: "AI Overview",
  training: "Model memory",
  read_not_cited: "Read, not cited",
  connect_logs: "Setup",
  strategy: "Focus",
  evidence: "Primary sources",
  meta: "Meta AI",
};
// Bad news kinds get the inverted block; everything else stays neutral.
const BAD_KINDS = new Set(["accuracy", "crawler_access", "broken_page", "refresh", "own_page"]);

const EVIDENCE: Record<string, { label: string; help: string }> = {
  official: { label: "Official", help: "the platform's own documentation" },
  strong: { label: "Strong", help: "controlled studies or large datasets agree" },
  moderate: { label: "Moderate", help: "consistent studies, some vendor-run" },
  emerging: { label: "Emerging", help: "early or correlational evidence" },
};

// What NOT to do, with the evidence. Static: these hold for every tenant.
const DONTS: { title: string; why: string }[] = [
  {
    title: "Publishing your own “best X” rankings",
    why: "Google's 2026 spam policies name self-ranked lists and scaled “alternatives” pages; engines discount them.",
  },
  {
    title: "Hidden instructions for AI (“Summarize with AI” prompts, invisible text)",
    why: "Microsoft calls this AI recommendation poisoning; an engine that spots it can drop the brand entirely.",
  },
  {
    title: "Fake or incentivized reviews",
    why: "Illegal under the FTC's fake-review rule, and review sites remove them.",
  },
  {
    title: "Spending time on llms.txt or special “AI schema”",
    why: "AI bots rarely request llms.txt, and Google says its AI features need no special markup.",
  },
  {
    title: "Mass-producing AI pages for every query",
    why: "Google's spam policies name scaled content abuse, and once every brand copies it, nobody gains.",
  },
];

export default async function RecommendationsPage() {
  const [me, recs] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<Recommendation[]>("/api/tenant/recommendations"),
  ]);
  if (recs.status === 403) {
    return (
      <NoOrgNotice
        active="Recommendations"
        isSuperadmin={me.data?.is_superadmin}
        detail={recs.error}
      />
    );
  }
  const items = recs.data ?? [];
  const isActive = (r: Recommendation) => r.status === "open" || r.status === "in_progress";
  const strategy = items.find((r) => r.branch === "strategy" && isActive(r));
  const active = items.filter((r) => isActive(r) && r !== strategy);
  const closed = items.filter((r) => !isActive(r));

  // The lead: how much is on the list, and the one to start.
  const top = strategy ?? active[0] ?? null;
  const openCount = items.filter((r) => r.status === "open").length;
  const inProgress = items.filter((r) => r.status === "in_progress").length;
  const lead =
    items.length === 0
      ? {
          tells: "No recommendations yet.",
          act: "Nothing to start yet.",
          tone: "neutral" as const,
        }
      : !top
        ? {
            tells: `All ${closed.length} recommendations are closed.`,
            act: "Nothing to start.",
            href: "/dashboard/action-plan",
            hrefLabel: "Action Plan",
            tone: "good" as const,
          }
        : {
            tells: (
              <>
                {openCount + inProgress} open; the top one is &ldquo;
                {top.title || KIND_LABELS[top.branch] || top.branch}&rdquo;.
              </>
            ),
            act: top.status === "in_progress" ? "Finish the one you started, then mark it done." : "Start the top one.",
            href: top.link || undefined,
            hrefLabel: "See the data",
            tone: (openCount + inProgress > 5 ? "bad" : "neutral") as "good" | "bad" | "neutral",
          };

  return (
    <main className="mx-auto max-w-5xl px-6 pb-16">
      <DashNav active="Recommendations" isSuperadmin={me.data?.is_superadmin} />
      <PageLead {...lead} />
      {strategy && (
        <section className="blueprint mb-8 grid-cols-1">
          <div>
            <div className="bp-bar">
              <span>Your focus right now</span>
              <EvidenceTag evidence={strategy.evidence} />
            </div>
            <div className="p-5">
              <h2 className="bp-head mb-2 text-xl">{strategy.title}</h2>
              <p className="mb-3 text-sm text-[var(--text)]">{strategy.action_text}</p>
              <Steps steps={strategy.steps} />
              <p className="mt-3 text-xs text-[var(--text-3)]">{strategy.why}</p>
            </div>
          </div>
        </section>
      )}

      {active.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">
            Needs action · {active.length}
          </h2>
          <ol className="space-y-4">
            {active.map((rec, i) => (
              <PlayCard key={rec.id} rec={rec} rank={i + 1} />
            ))}
          </ol>
        </section>
      )}

      <section className="blueprint mb-8 grid-cols-1">
        <div>
          <div className="bp-bar">
            <span>Don&apos;t</span>
            <span>Wastes time or backfires</span>
          </div>
          <ul>
            {DONTS.map((d) => (
              <li key={d.title} className="border-t border-[var(--line)] px-4 py-3 first:border-t-0">
                <p className="text-[13px] font-semibold">{d.title}</p>
                <p className="text-xs text-[var(--text-3)]">{d.why}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {closed.length > 0 && (
        <details className="mb-8">
          <summary className="mb-3 cursor-pointer text-sm font-medium text-[var(--text-2)]">
            Closed · {closed.length}
          </summary>
          <ul className="space-y-2">
            {closed.map((rec) => (
              <li key={rec.id} className="card flex flex-wrap items-center justify-between gap-3 p-3">
                <span className="text-sm">
                  {rec.title || rec.action_text}
                  <span className="ml-2 text-xs text-[var(--text-3)]">
                    {rec.status === "resolved" ? "resolved by the data" : rec.status}
                  </span>
                </span>
                <StatusButtons id={rec.id} status={rec.status} compact />
              </li>
            ))}
          </ul>
        </details>
      )}
    </main>
  );
}

function PlayCard({ rec, rank }: { rec: Recommendation; rank: number }) {
  const kind = KIND_LABELS[rec.branch] ?? rec.branch;
  return (
    <li className="card p-4">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--plane-2)] text-[11.5px] font-semibold tabular-nums text-[var(--text-2)]">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`chip ${BAD_KINDS.has(rec.branch) ? "text-[var(--neg)]" : ""}`}>{kind}</span>
            {rec.status === "in_progress" && <span className="chip">In progress</span>}
            <EvidenceTag evidence={rec.evidence} />
          </div>
          <h3 className="mt-1.5 text-[16px] font-semibold leading-snug">{rec.title || kind}</h3>
          <p className="mt-1 text-[13.5px] leading-snug text-[var(--text-2)]">
            <Linkify text={rec.action_text} />
          </p>
          <Steps steps={rec.steps} />
          {rec.why && (
            <p className="mt-2 line-clamp-1 text-[12px] text-[var(--text-3)]" title={rec.why}>
              {rec.why}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <StatusButtons id={rec.id} status={rec.status} />
          {rec.link && (
            <Link href={rec.link} className="text-xs font-medium text-[var(--accent-2)] hover:underline">
              See the data →
            </Link>
          )}
        </div>
      </div>
    </li>
  );
}

function Steps({ steps }: { steps: string[] | null }) {
  if (!steps || steps.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1">
      {steps.map((s, i) => (
        <li key={s} className="flex gap-2 text-[13px] leading-snug text-[var(--text-2)]">
          <span className="w-4 shrink-0 text-right tabular-nums text-[var(--text-3)]">{i + 1}.</span>
          <span><Linkify text={s} /></span>
        </li>
      ))}
    </ul>
  );
}

function EvidenceTag({ evidence }: { evidence: string }) {
  const e = EVIDENCE[evidence];
  if (!e) return null;
  return (
    <span className="text-[11.5px] text-[var(--text-3)]" title={e.help}>
      Evidence: {e.label}
    </span>
  );
}
