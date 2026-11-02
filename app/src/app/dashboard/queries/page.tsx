import Link from "next/link";
import {
  apiFetch,
  rangeQuery,
  type Me,
  type QueriesIntelPayload,
  type QueryControlsPayload,
} from "@/lib/api";
import { ActiveToggle, PersonaPicker } from "./query-controls";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { LIKELIHOOD_COLORS, LIKELIHOOD_LABELS, surfaceLabel, humanize } from "@/lib/viz";

function ClassificationChip({
  classification,
}: {
  classification: { web_search_likelihood: string; signals: Record<string, number> } | null;
}) {
  if (!classification) {
    return <span className="text-xs text-[var(--text-3)]">not classified yet</span>;
  }
  const bucket = classification.web_search_likelihood;
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-[var(--text)]"
      title={`signals: ${JSON.stringify(classification.signals)}`}
    >
      <span
        className="inline-block h-2.5 w-2.5 rounded-full"
        style={{ background: LIKELIHOOD_COLORS[bucket] ?? "var(--border-strong)" }}
      />
      {LIKELIHOOD_LABELS[bucket] ?? bucket}
    </span>
  );
}

function ModeLinks({
  entries,
}: {
  entries: [string, { result_id: number; run_id: number; status: string }][];
}) {
  if (entries.length === 0) {
    return <span className="text-xs text-[var(--text-3)]">no results yet</span>;
  }
  return (
    <div className="flex flex-col gap-1">
      {entries.map(([surface, result]) =>
        result.status === "ok" ? (
          <Link
            key={surface}
            href={`/dashboard/runs/${result.run_id}/results/${result.result_id}`}
            className="text-xs text-[var(--accent)] hover:underline"
          >
            {surfaceLabel(surface)}
          </Link>
        ) : (
          // A failed capture is missing data, not bad news about the brand:
          // quiet text, not the bad-news pill.
          <span key={surface} className="text-xs text-[var(--text-3)]">
            {surfaceLabel(surface)}: no answer
          </span>
        ),
      )}
    </div>
  );
}

export default async function QueriesPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, intel, controls] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<QueriesIntelPayload>(`/api/tenant/queries-intel${rangeQuery(from, to)}`),
    apiFetch<QueryControlsPayload>("/api/tenant/query-controls"),
  ]);
  if (intel.status === 403) {
    return (
      <NoOrgNotice active="Queries" isSuperadmin={me.data?.is_superadmin} detail={intel.error} />
    );
  }
  const queries = intel.data?.queries ?? [];
  const activeQueries = queries.filter((q) => q.active);
  const pausedQueries = queries.filter((q) => !q.active);
  const ctl = controls.data ?? null;

  // The lead: how many questions you're in the latest answer for, how many
  // you're missing, and the one thing to do with the list.
  const answered = activeQueries.filter((q) => Object.keys(q.latest_results).length > 0);
  const named = answered.filter((q) => Object.values(q.latest_results).some((r) => r.brand_mentioned));
  const missing = answered.length - named.length;
  const firstMissing = answered.find((q) => !Object.values(q.latest_results).some((r) => r.brand_mentioned));
  const lead =
    queries.length === 0
      ? {
          tells: "No questions are set up yet. These are the questions your buyers ask AI; every rate in the product is measured against this list.",
          act: "Your EverPresent contact drafts the list with you, usually 25 to 50 questions. Once it's in, the first run asks every engine.",
          tone: "neutral" as const,
        }
      : answered.length === 0
        ? {
            tells: `${activeQueries.length} questions are tracked. None has an answer yet; the first run fills this table.`,
            act: "Read the list as your buyer would. Pause anything that isn't a question a buyer asks about your category, and the rates will follow the set.",
            tone: "neutral" as const,
          }
        : {
            tells: (
              <>
                You&apos;re named in the latest answer for {named.length} of {answered.length} questions
                {missing > 0 ? <> and missing from {missing}</> : null}
                {pausedQueries.length > 0 ? <>; {pausedQueries.length} paused</> : null}.
              </>
            ),
            act:
              missing === 0
                ? "You're in every answer measured. Use this page to read what the engines say and to keep the question set honest: pause the ones that stop mattering."
                : "Open a question you're missing and read the answer a buyer gets; the rival it names is who you're losing to. Pause questions that aren't yours, and the rates follow the set.",
            href: firstMissing
              ? (() => {
                  const ok = Object.values(firstMissing.latest_results).find((r) => r.status === "ok");
                  return ok ? `/dashboard/runs/${ok.run_id}/results/${ok.result_id}` : undefined;
                })()
              : undefined,
            hrefLabel: "Read a missed answer",
            tone: (missing === 0 ? "good" : missing > named.length ? "bad" : "neutral") as "good" | "bad" | "neutral",
          };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Queries" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      <section className="card p-4">
        <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">
          Tracked questions and the latest answer to each
        </h2>
        {queries.length === 0 ? (
          <p className="text-sm text-[var(--text-3)]">No queries configured.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm min-w-[760px]">
              <thead className="text-[var(--text-2)]">
                <tr>
                  <th className="py-2 pr-4">Query</th>
                  <th className="pr-4">Question set</th>
                  <th className="pr-4">Web search</th>
                  <th className="pr-4">Brand in answer</th>
                  <th className="pr-4">API answers</th>
                  <th className="pr-4">Website answers</th>
                  <th className="pr-4">Compare</th>
                  <th className="pr-4">Personas</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {activeQueries.map((query) => {
                  const surfaces = Object.entries(query.latest_results);
                  const modeA = surfaces.filter(([, r]) => r.mode === "A");
                  const modeB = surfaces.filter(([, r]) => r.mode === "B");
                  const comparable =
                    modeA.find(([, r]) => r.status === "ok") &&
                    modeB.find(([, r]) => r.status === "ok");
                  return (
                    <tr key={query.id} className="border-t border-[var(--border)] align-top">
                      <td className="max-w-md py-3 pr-4">
                        {query.text}
                        {query.branded && (
                          <span
                            className="chip ml-2 align-middle"
                            title="Branded query. Measured on the Brand tab and excluded from competitive visibility."
                          >
                            branded
                          </span>
                        )}
                      </td>
                      <td className="pr-4 text-[var(--text-2)]">{humanize(query.corpus_tag)}</td>
                      <td className="pr-4">
                        <ClassificationChip classification={query.classification} />
                      </td>
                      <td className="pr-4">
                        {surfaces.length === 0 ? (
                          <span className="text-[var(--text-3)]">—</span>
                        ) : surfaces.some(([, r]) => r.brand_mentioned) ? (
                          <span className="text-[var(--pos)]">yes</span>
                        ) : (
                          <span className="text-[var(--warn-t)]">no</span>
                        )}
                      </td>
                      <td className="pr-4">
                        <ModeLinks entries={modeA} />
                      </td>
                      <td className="pr-4">
                        <ModeLinks entries={modeB} />
                      </td>
                      <td>
                        {comparable ? (
                          <Link
                            href={`/dashboard/compare?a=${
                              modeA.find(([, r]) => r.status === "ok")![1].result_id
                            }&b=${modeB.find(([, r]) => r.status === "ok")![1].result_id}`}
                            className="text-xs text-[var(--accent)] hover:underline"
                          >
                            API vs website
                          </Link>
                        ) : (
                          <span className="text-xs text-[var(--text-3)]">—</span>
                        )}
                      </td>
                      <td className="pr-4">
                        {ctl ? (
                          <PersonaPicker
                            id={query.id}
                            chosen={query.persona_segments ?? []}
                            controls={ctl}
                          />
                        ) : (
                          <span className="text-xs text-[var(--text-3)]">—</span>
                        )}
                      </td>
                      <td>
                        <ActiveToggle id={query.id} active={true} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <details className="mt-4">
          <summary className="cursor-pointer text-xs font-medium text-[var(--text-3)] hover:text-[var(--text-2)]">
            How to read this table
          </summary>
          <p className="mt-2 max-w-3xl text-xs leading-relaxed text-[var(--text-3)]">
            Web search is how likely an engine is to search the web for a question instead of
            answering from memory, judged by comparing its answers with and without search. Answers
            come from two places: the engines&apos; developer APIs (more answers) and their public
            websites (closest to what a signed-out, free-tier user sees: no memory, ads possible).
            Compare puts the two side by side.
          </p>
        </details>
        {ctl && ctl.selective && ctl.personas.length > 0 && (
          <p className="mt-3 text-xs text-[var(--text-3)]">
            Every question runs on the generic baseline. Tick a persona to also ask it as that
            buyer; persona answers are reported on the Personas page.
            {ctl.unlock_plan && (
              <>
                {" "}Greyed personas are outside the {ctl.plan} plan and open up on {ctl.unlock_plan}.
              </>
            )}
          </p>
        )}
      </section>

      {pausedQueries.length > 0 && (
        <section className="card mt-6 p-4">
          <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">Paused questions</h2>
          <p className="mb-3 text-xs text-[var(--text-3)]">
            A paused question is left out of runs and of the rates from the day it was paused.
            Its earlier answers stay in the history.
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-[var(--text-2)]">
              <tr>
                <th className="py-2 pr-4">Query</th>
                <th className="pr-4">Question set</th>
                <th className="pr-4">Stopped</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pausedQueries.map((query) => (
                <tr key={query.id} className="border-t border-[var(--border)] align-top">
                  <td className="max-w-md py-3 pr-4 text-[var(--text-2)]">{query.text}</td>
                  <td className="pr-4 text-[var(--text-3)]">{humanize(query.corpus_tag)}</td>
                  <td className="pr-4 text-xs text-[var(--text-3)]">
                    {query.paused_at
                      ? `Data collection stopped on ${query.paused_at.slice(0, 10)} (paused by ${
                          query.paused_by === "admin" ? "EverPresent" : "you"
                        })`
                      : "Not collected (inactive in the config)"}
                  </td>
                  <td>
                    <ActiveToggle id={query.id} active={false} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
