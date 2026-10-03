import Link from "next/link";
import { apiFetch, type Me, type Recommendation } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { setRecommendationStatus } from "./actions";

const KIND_LABELS: Record<string, string> = {
  accuracy: "Wrong fact",
  crawler_access: "Bot access",
  broken_page: "Broken page",
  refresh: "Lost citation",
  subquery: "Sub-question",
  reviews: "Reviews",
  earned: "Earned media",
  owned: "Your site",
  community: "Community",
  reference: "Reference",
  web_search: "Query gap",
  aio: "AI Overview",
  training: "Model memory",
  read_not_cited: "Read, not cited",
  connect_logs: "Setup",
  strategy: "Focus",
};
// Bad news kinds get the inverted block; everything else stays neutral.
const BAD_KINDS = new Set(["accuracy", "crawler_access", "broken_page", "refresh"]);

const EVIDENCE: Record<string, { label: string; help: string }> = {
  official: { label: "Official", help: "the platform's own documentation" },
  strong: { label: "Strong", help: "controlled studies or large datasets agree" },
  moderate: { label: "Moderate", help: "consistent studies, some vendor-run" },
  emerging: { label: "Emerging", help: "early or correlational evidence" },
};

const NEXT_ACTIONS: Record<string, { to: Recommendation["status"]; label: string }[]> = {
  open: [
    { to: "in_progress", label: "Start" },
    { to: "dismissed", label: "Dismiss" },
  ],
  in_progress: [
    { to: "done", label: "Mark done" },
    { to: "open", label: "Back to open" },
  ],
  done: [{ to: "open", label: "Reopen" }],
  dismissed: [{ to: "open", label: "Reopen" }],
  resolved: [],
};

// What NOT to do, with the evidence. Static: these hold for every tenant.
const DONTS: { title: string; why: string }[] = [
  {
    title: "Publishing your own “best X” rankings",
    why: "Third-party lists drove ~86% of brand mentions in September 2026 tests; brands' own lists 14%. Google's Aug and Sept 2026 spam updates target self-promotional listicles.",
  },
  {
    title: "Hidden instructions for AI (“Summarize with AI” prompts, invisible text)",
    why: "Microsoft flagged this as AI recommendation poisoning. In a 2026 test, one injected page dropped a brand from 54% to 0% of Claude's top picks.",
  },
  {
    title: "Fake or incentivised reviews",
    why: "Illegal under the FTC's fake-review rule, and review sites remove them. Real rating gaps are what move AI picks.",
  },
  {
    title: "Spending time on llms.txt or special “AI schema”",
    why: "No measured effect: 97% of llms.txt files got zero requests (Ahrefs, 2026), and Google says AI features need no special markup.",
  },
  {
    title: "Mass-producing AI pages for every query",
    why: "Scaled content is a named spam target, and when every brand copies the same tactic the gain drops to almost zero.",
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

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-8">
      <DashNav active="Recommendations" isSuperadmin={me.data?.is_superadmin} />
      <p className="mb-6 max-w-3xl text-sm text-[var(--text-2)]">
        Your playbook, ranked. Every play comes from your own measurements and is graded by how
        strong the evidence behind it is (as of October 2026). Getting found by the engines' searches
        comes first, then explicit facts and third-party proof; formatting comes last.
      </p>

      {items.length === 0 && (
        <section className="card p-4">
          <p className="text-sm text-[var(--text-2)]">
            No recommendations yet. They appear after the first run is processed.
          </p>
        </section>
      )}

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
                <StatusButtons rec={rec} />
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
    <li className="blueprint grid-cols-1">
      <div>
        <div className="bp-bar">
          <span>
            #{rank} · {kind}
            {rec.status === "in_progress" && " · in progress"}
          </span>
          <EvidenceTag evidence={rec.evidence} />
        </div>
        <div className="p-4">
          <h3 className="mb-1 text-[15px] font-semibold">
            {BAD_KINDS.has(rec.branch) ? <span className="bp-neg">{rec.title}</span> : rec.title || kind}
          </h3>
          <p className="mb-3 text-sm leading-relaxed text-[var(--text)]">{rec.action_text}</p>
          <Steps steps={rec.steps} />
          {rec.why && (
            <p className="mt-3 text-xs text-[var(--text-3)]">
              <span className="font-semibold">Why: </span>
              {rec.why}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusButtons rec={rec} />
            {rec.link && (
              <Link href={rec.link} className="ml-auto text-xs text-[var(--accent)]">
                See the data →
              </Link>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

function Steps({ steps }: { steps: string[] | null }) {
  if (!steps || steps.length === 0) return null;
  return (
    <ol className="list-decimal space-y-1 pl-5 text-sm text-[var(--text-2)]">
      {steps.map((s) => (
        <li key={s}>{s}</li>
      ))}
    </ol>
  );
}

function EvidenceTag({ evidence }: { evidence: string }) {
  const e = EVIDENCE[evidence];
  if (!e) return <span />;
  return <span title={e.help}>Evidence: {e.label}</span>;
}

function StatusButtons({ rec }: { rec: Recommendation }) {
  const actions = NEXT_ACTIONS[rec.status] ?? [];
  if (actions.length === 0) return null;
  return (
    <>
      {actions.map(({ to, label }) => (
        <form key={to} action={setRecommendationStatus.bind(null, rec.id, to)}>
          <button className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-2)]">
            {label}
          </button>
        </form>
      ))}
    </>
  );
}
