import Link from "next/link";
import { apiFetch, type Me, type RecImpact, type RecTarget, type Recommendation } from "@/lib/api";
import {
  AREAS,
  AREA_LABEL,
  BAND_BARS,
  BAND_LABEL,
  CONTROL_HELP,
  CONTROL_LABEL,
  EFFORT_LABEL,
  EVIDENCE,
  OFF_SITE_AREAS,
  SPEED_LABEL,
} from "@/lib/recs";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { DoneForm, StatusButtons } from "@/components/plan-buttons";
import { ExtLink, Linkify } from "@/components/ui";

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
    title: "Buying links or mass-submitting to directories",
    why: "We recommend a site only when AI already cites it for your questions. A link from a site it never cites is not a measured route into answers.",
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

// Why a third-party site is on the list at all, and what each play commits to.
const OFF_SITE_NOTE =
  "A site outside your own is listed only when AI cited it for your questions in at least 3 " +
  "answers, in 2 or more runs, while naming your rivals. Each one names the pages and says what " +
  "is realistic there: a profile you can claim, a thread you can answer, a list with a way in, " +
  "or an article that won't change.";

const isActive = (r: Recommendation) => r.status === "open" || r.status === "in_progress";
const score = (r: Recommendation) => r.impact?.score ?? 0;

export default async function RecommendationsPage({
  searchParams,
}: {
  searchParams: Promise<{ area?: string }>;
}) {
  const [{ area }, me, recs] = await Promise.all([
    searchParams,
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
  const focus = items.find((r) => r.branch === "strategy" && isActive(r));
  const setup = items.filter((r) => r.category === "setup" && isActive(r));
  // The ranked list: everything open that is a task. Highest projected
  // impact first; plays added by hand carry no projection and keep the
  // place their priority gives them.
  const ranked = items
    .filter((r) => isActive(r) && r.branch !== "strategy" && r.category !== "setup")
    .sort((a, b) => b.priority - a.priority || score(b) - score(a));
  const rankOf = new Map(ranked.map((r, i) => [r.id, i + 1]));
  const closed = items.filter((r) => !isActive(r));

  const activeArea = AREAS.find((a) => a.key === area)?.key ?? null;
  const shown = activeArea ? ranked.filter((r) => r.category === activeArea) : ranked;
  const byArea = new Map<string, Recommendation[]>();
  for (const r of ranked) byArea.set(r.category, [...(byArea.get(r.category) ?? []), r]);
  const areasOpen = AREAS.filter((a) => byArea.has(a.key)).length;

  const top = ranked[0] ?? null;
  const lead =
    items.length === 0
      ? { tells: "No recommendations yet.", act: "Nothing to start yet.", tone: "neutral" as const }
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
                {ranked.length} open across {areasOpen} {areasOpen === 1 ? "area" : "areas"}; the
                biggest is &ldquo;{top.title}&rdquo;.
              </>
            ),
            act:
              top.status === "in_progress"
                ? "Finish the one you started, then mark it done."
                : "Start the top one.",
            href: top.link || undefined,
            hrefLabel: "See the data",
            tone: "neutral" as const,
          };

  return (
    <main className="mx-auto max-w-5xl px-6 pb-16">
      <DashNav active="Recommendations" isSuperadmin={me.data?.is_superadmin} />
      <PageLead {...lead} />

      {focus && (
        <p className="card mb-6 px-5 py-3 text-[13.5px] leading-snug text-[var(--text-2)]">
          <span className="font-semibold text-[var(--text)]">{focus.title}.</span>{" "}
          {focus.action_text}
        </p>
      )}

      {ranked.length > 0 && (
        <nav aria-label="Areas" className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <AreaCard
            href="/dashboard/recommendations"
            label="All areas"
            asks="Everything, by projected impact"
            count={ranked.length}
            band={top?.impact?.band}
            active={!activeArea}
          />
          {AREAS.map((a) => {
            const list = byArea.get(a.key) ?? [];
            return (
              <AreaCard
                key={a.key}
                href={`/dashboard/recommendations?area=${a.key}`}
                label={a.label}
                asks={a.asks}
                count={list.length}
                band={list[0]?.impact?.band}
                active={activeArea === a.key}
              />
            );
          })}
        </nav>
      )}

      {shown.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
            {activeArea ? `${AREA_LABEL[activeArea]} · ${shown.length}` : `Needs action · ${shown.length}`}
            <span className="font-normal text-[var(--text-3)]"> · ranked by projected impact</span>
          </h2>
          <details className="mb-3 text-[12.5px] leading-relaxed text-[var(--text-3)]">
            <summary className="cursor-pointer hover:text-[var(--text-2)]">How this is ranked</summary>
            <div className="mt-2 max-w-[75ch] space-y-2">
              <p>
                Projected impact is how much of your audience the answers reach, times how often
                you&apos;re missing from them, times how likely the fix is to work. The first two
                are counted from your last 28 days of answers, weighted by engine audience like
                your headline rate; each card says what it counted.
              </p>
              <p>
                How likely the fix is to work is our judgement of two things shown on every card:
                who has to act (you, someone you can ask, or someone who has to choose you) and
                how strong the evidence for the tactic is.
              </p>
              <p>
                High marks the recommendations that together carry the first half of the
                projected impact on this list, medium the next third, low the rest. Use it to
                decide what to do first; it does not predict how many points you will gain.
              </p>
              {!activeArea && <p>{OFF_SITE_NOTE}</p>}
            </div>
          </details>
          {activeArea && OFF_SITE_AREAS.has(activeArea) && (
            <p className="mb-3 max-w-[75ch] text-[12.5px] leading-relaxed text-[var(--text-3)]">
              {OFF_SITE_NOTE}
            </p>
          )}
          <ol className="space-y-4">
            {shown.map((rec) => (
              <PlayCard key={rec.id} rec={rec} rank={rankOf.get(rec.id) ?? 0} />
            ))}
          </ol>
        </section>
      )}
      {activeArea && shown.length === 0 && (
        <p className="card mb-8 p-5 text-sm text-[var(--text-2)]">
          Nothing open in {AREA_LABEL[activeArea].toLowerCase()}.
        </p>
      )}

      {setup.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">Worth knowing · {setup.length}</h2>
          <p className="mb-3 text-[12.5px] text-[var(--text-3)]">
            These change what we can measure or how to read it. They carry no projected impact.
          </p>
          <ul className="space-y-2">
            {setup.map((rec) => (
              <li key={rec.id} className="card flex flex-wrap items-center justify-between gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold">{rec.title}</p>
                  <p className="mt-0.5 text-[13px] text-[var(--text-2)]">{rec.action_text}</p>
                  <Steps steps={rec.steps} />
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <StatusButtons id={rec.id} status={rec.status} compact />
                  {rec.link && (
                    <Link href={rec.link} className="text-xs font-medium text-[var(--accent-2)] hover:underline">
                      See the data →
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
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

function AreaCard({
  href,
  label,
  asks,
  count,
  band,
  active,
}: {
  href: string;
  label: string;
  asks: string;
  count: number;
  band?: RecImpact["band"];
  active: boolean;
}) {
  const body = (
    <>
      <span className="flex items-baseline justify-between gap-2">
        <span className="text-[13.5px] font-semibold leading-tight text-[var(--text)]">{label}</span>
        <span className="text-[13px] font-semibold tabular-nums text-[var(--text)]">{count || ""}</span>
      </span>
      <span className="mt-0.5 hidden text-[12px] leading-snug text-[var(--text-3)] sm:block">{asks}</span>
      <span className="mt-2 flex items-center gap-1.5 text-[11.5px] text-[var(--text-2)]">
        {count > 0 && band ? (
          <>
            <Meter band={band} />
            Top: {BAND_LABEL[band].toLowerCase()}
          </>
        ) : count > 0 ? (
          "Open"
        ) : (
          "Nothing open"
        )}
      </span>
    </>
  );
  const box = `block rounded-[6px] border px-3 py-2.5 ${
    active
      ? "border-[var(--text)] bg-[var(--surface)]"
      : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)]"
  }`;
  if (count === 0 && !active) {
    return <span className={`${box} opacity-60`}>{body}</span>;
  }
  return (
    <Link href={href} className={box} aria-current={active ? "true" : undefined} scroll={false}>
      {body}
    </Link>
  );
}

/** Three bars, filled by band. Ink, not orange: impact is a size, not good news. */
function Meter({ band }: { band: NonNullable<RecImpact["band"]> }) {
  const filled = BAND_BARS[band] ?? 0;
  return (
    <span className="inline-flex items-end gap-[2px]" aria-hidden>
      {[1, 2, 3].map((i) => (
        <span
          key={i}
          className={`w-[4px] rounded-[1px] ${i <= filled ? "bg-[var(--text)]" : "bg-[var(--border)]"}`}
          style={{ height: 4 + i * 3 }}
        />
      ))}
    </span>
  );
}

function PlayCard({ rec, rank }: { rec: Recommendation; rank: number }) {
  const areaLabel = AREA_LABEL[rec.category] ?? (rec.branch === "manual" ? "Added by you" : "");
  const band = rec.impact?.band;
  const evidence = EVIDENCE[rec.evidence];
  const facts: { label: string; value: string; help?: string }[] = [
    rec.control && {
      label: "Who acts",
      value: CONTROL_LABEL[rec.control] ?? rec.control,
      help: CONTROL_HELP[rec.control],
    },
    rec.effort && { label: "Effort", value: EFFORT_LABEL[rec.effort] ?? rec.effort },
    rec.speed && { label: "Shows in", value: SPEED_LABEL[rec.speed] ?? rec.speed },
    evidence && { label: "Evidence", value: evidence.label, help: evidence.help },
  ].filter(Boolean) as { label: string; value: string; help?: string }[];
  return (
    <li className="card p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--plane-2)] text-[11.5px] font-semibold tabular-nums text-[var(--text-2)]">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {areaLabel && <span className="chip">{areaLabel}</span>}
            {rec.status === "in_progress" && <span className="chip">In progress</span>}
            {band && (
              <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--text)]">
                <Meter band={band} />
                {BAND_LABEL[band]}
              </span>
            )}
          </div>
          <h3 className="mt-1.5 text-[16px] font-semibold leading-snug">{rec.title || areaLabel}</h3>
          {rec.impact?.basis && (
            <p className="mt-1 text-[12.5px] leading-snug text-[var(--text-3)]">{rec.impact.basis}</p>
          )}
          <p className="mt-2 text-[13.5px] leading-snug text-[var(--text-2)]">
            <Linkify text={rec.action_text} />
          </p>

          {facts.length > 0 && (
            <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]">
              {facts.map((f) => (
                <div key={f.label} className="flex gap-1.5" title={f.help}>
                  <dt className="text-[var(--text-3)]">{f.label}</dt>
                  <dd className="font-medium text-[var(--text)]">{f.value}</dd>
                </div>
              ))}
            </dl>
          )}

          <Targets targets={rec.targets} />

          {rec.steps && rec.steps.length > 0 && (
            <>
              <p className="bp-label mt-3">What to do</p>
              <Steps steps={rec.steps} />
            </>
          )}
          {rec.why && (
            <p className="mt-3 text-[12px] leading-snug text-[var(--text-3)]">
              <span className="font-medium">Why this works:</span> {rec.why}
            </p>
          )}
        </div>
      </div>
      <div className="mt-4 border-t border-[var(--line)] pt-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <StatusButtons id={rec.id} status={rec.status} withoutDone />
          {rec.link && (
            <Link href={rec.link} className="text-xs font-medium text-[var(--accent-2)] hover:underline">
              See the data →
            </Link>
          )}
        </div>
        {/* Done is where the measurement starts: it asks what changed, where and when. */}
        <div className="mt-2">
          <DoneForm
            id={rec.id}
            primary={rec.status === "in_progress"}
            defaultUrl={rec.targets?.find((t) => t.kind === "Your page" && t.url)?.url ?? ""}
          />
        </div>
      </div>
    </li>
  );
}

/** The concrete things a play is about: the cited pages, your page, the
 * sub-questions. This is what makes it a task and not advice. */
function Targets({ targets }: { targets: RecTarget[] | null }) {
  if (!targets || targets.length === 0) return null;
  return (
    <>
      <p className="bp-label mt-3">Where exactly</p>
      <ul className="mt-1.5 divide-y divide-[var(--line)] rounded-[6px] border border-[var(--border)]">
        {targets.map((t, i) => (
          <li
            key={`${t.label}-${i}`}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2 text-[12.5px] leading-snug"
          >
            {t.kind && <span className="w-28 shrink-0 text-[var(--text-3)]">{t.kind}</span>}
            <span className="min-w-0 flex-1 basis-[12rem] break-all font-medium text-[var(--text)]">
              {t.url ? (
                <ExtLink href={t.url} className="!whitespace-normal">
                  {t.label}
                </ExtLink>
              ) : (
                t.label
              )}
            </span>
            {t.detail && (
              <span className="shrink-0 whitespace-nowrap tabular-nums text-[var(--text-2)]">{t.detail}</span>
            )}
            {t.note && (
              <span className={`w-full text-[var(--text-3)] ${t.kind ? "sm:pl-[7.75rem]" : ""}`}>{t.note}</span>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function Steps({ steps }: { steps: string[] | null }) {
  if (!steps || steps.length === 0) return null;
  return (
    <ol className="mt-1.5 space-y-1">
      {steps.map((s, i) => (
        <li key={s} className="flex gap-2 text-[13px] leading-snug text-[var(--text-2)]">
          <span className="w-4 shrink-0 text-right tabular-nums text-[var(--text-3)]">{i + 1}.</span>
          <span>
            <Linkify text={s} />
          </span>
        </li>
      ))}
    </ol>
  );
}
