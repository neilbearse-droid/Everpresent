import {
  apiFetch,
  rangeQuery,
  type AdsReport,
  type EngineModesPayload,
  type EngineScorecard,
  type Me,
  type RoutingReport,
} from "@/lib/api";
import { AdsSection } from "./ads";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { HBars } from "@/components/charts";
import { EngineStrip } from "@/components/engine-modes";
import { EngineMark, Linkify } from "@/components/ui";
import { AddToPlan } from "@/components/plan-buttons";
import { surfaceLabel } from "@/lib/viz";

const DIAGNOSIS_ORDER = ["knowledge_gap", "content_gap", "undetermined", "visible"];
const DIAGNOSIS_STYLE: Record<string, { chip: string; dot: string }> = {
  visible: { chip: "text-[var(--pos)]", dot: "bg-[var(--pos)]" },
  content_gap: { chip: "text-[var(--warn-t)]", dot: "bg-[var(--warn)]" },
  // Bad news: the chip is the ink pill; its dot is drawn in the pill's text
  // colour so it stays visible on the ink.
  knowledge_gap: { chip: "bp-neg", dot: "bg-[var(--ink-text)]" },
  undetermined: { chip: "text-[var(--text-2)]", dot: "bg-[var(--text-3)]" },
};

const CELL_STYLE: Record<string, string> = {
  brand: "bg-[var(--accent)] text-[var(--accent-ink)]",
  competitor: "bg-[var(--ink)] text-[var(--ink-text)]",
  absent: "bg-[var(--surface-2)] text-[var(--text-3)]",
};
const CELL_LABEL: Record<string, string> = { brand: "You", competitor: "Rival", absent: "—" };
const short = (t: string, n = 44) => (t.length > n ? t.slice(0, n - 1) + "…" : t);

export default async function EnginesPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, card, routing, ads, modes] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<EngineScorecard>(`/api/tenant/engine-scorecard${rangeQuery(from, to)}`),
    apiFetch<RoutingReport>(`/api/tenant/routing${rangeQuery(from, to)}`),
    apiFetch<AdsReport>("/api/tenant/ads"),
    apiFetch<EngineModesPayload>(`/api/tenant/engine-modes${rangeQuery(from, to)}`),
  ]);
  if (card.status === 403) {
    return <NoOrgNotice active="Engines" isSuperadmin={me.data?.is_superadmin} detail={card.error} />;
  }
  const data = card.data;
  const engines = data?.engines ?? [];
  const matrix = data?.matrix ?? [];
  const surfaces = engines.map((e) => e.surface);
  const summary = data?.diagnosis_summary ?? {};

  // The lead: where you're named least, and which kind of gap to close first.
  const byRate = [...engines].sort((a, b) => b.brand_rate - a.brand_rate);
  const best = byRate[0];
  const worst = byRate[byRate.length - 1];
  const knowledge = summary.knowledge_gap ?? 0;
  const content = summary.content_gap ?? 0;
  const gaps = knowledge + content;
  const brand = data?.brand_name ?? "You";
  const lead =
    engines.length === 0
      ? { tells: "No engine answers yet.", act: "Nothing to do until the first run.", tone: "neutral" as const }
      : gaps === 0
        ? {
            tells: `${brand} is named on every question, on every engine.`,
            act: "Hold what's winning.",
            tone: "good" as const,
          }
        : {
            tells:
              engines.length > 1
                ? `${brand} is named most on ${surfaceLabel(best.surface)} (${best.brand_rate}%), least on ${surfaceLabel(worst.surface)} (${worst.brand_rate}%).`
                : `${brand} is named on ${best.brand_rate}% of questions on ${surfaceLabel(best.surface)}.`,
            act:
              knowledge >= content
                ? `Close the ${knowledge} knowledge gaps first: get covered on the sites engines cite.`
                : `Close the ${content} content gaps first: fix the pages behind them.`,
            href: knowledge >= content ? "/dashboard/action-plan" : "/dashboard/pages",
            hrefLabel: knowledge >= content ? "Action Plan" : "Your Pages",
            tone: (gaps > engines.length ? "bad" : "neutral") as "good" | "bad" | "neutral",
          };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Engines" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      {modes.data?.observed && (
        <section className="mb-6">
          <h2 className="mb-3 text-[15px] font-semibold tracking-[-0.01em]">By engine</h2>
          <EngineStrip data={modes.data} />
        </section>
      )}

      {routing.data?.observed && (
        <section className="mb-6 card p-4">
          <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">
            Searched the web before answering
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {routing.data.engines.map((e) => (
              <div key={e.surface} className="card-inset p-4">
                <div className="text-3xl font-semibold tabular-nums text-[var(--text)]">
                  {e.search_rate}%
                </div>
                <div className="mt-1 flex items-center gap-2 text-sm font-medium text-[var(--text)]">
                  <EngineMark surface={e.surface} size={16} />
                  {surfaceLabel(e.surface)}
                </div>
                <div className="text-xs text-[var(--text-3)]">
                  {e.searched}/{e.measured} questions searched
                  {e.from_probe ? " · measured without forced search" : ""}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {engines.length === 0 ? (
        <section className="card p-4">
          <h2 className="mb-2 text-lg font-medium">No engine data yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            Appears after the first completed run.
          </p>
        </section>
      ) : (
        <>
          {/* Per-engine visibility */}
          <section className="mb-6 card p-4">
            <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
              Where {data!.brand_name} shows up, by engine
            </h2>
            <HBars
              items={engines.map((e) => ({
                label: `${surfaceLabel(e.surface)} · ${e.brand_present}/${e.queries_measured}`,
                value: e.brand_rate,
                color: "var(--text)",
              }))}
              max={100}
              unit="%"
            />
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {engines.map((e) => (
                <div key={e.surface} className="rounded-md border border-[var(--border)] p-3 text-sm">
                  <div className="flex items-center gap-2 font-medium">
                    <EngineMark surface={e.surface} size={18} />
                    {surfaceLabel(e.surface)}
                  </div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">{e.brand_rate}%</div>
                  <div className="text-xs text-[var(--text-3)]">mentioned</div>
                  <div className="mt-1.5 flex items-baseline gap-1.5">
                    <span className="text-sm font-semibold tabular-nums text-[var(--text-2)]">
                      {e.citation_rate}%
                    </span>
                    <span className="text-xs text-[var(--text-3)]">cited (linked)</span>
                  </div>
                  {e.mention_citation_gap >= 10 && (
                    <div className="mt-1 text-xs text-[var(--warn-t)]">
                      Named but not linked ({e.mention_citation_gap} pt gap)
                    </div>
                  )}
                  <div className="mt-1 text-xs text-[var(--text-3)]">
                    {e.top_competitor
                      ? `Top rival cited: ${e.top_competitor}`
                      : "No rival cited"}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Diagnosis summary */}
          <section className="mb-6 card p-4">
            <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">Why you're missing</h2>
            <div className="flex flex-wrap gap-3">
              {DIAGNOSIS_ORDER.filter((t) => summary[t]).map((t) => (
                <div
                  key={t}
                  className="flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-sm"
                >
                  <span className={`h-2.5 w-2.5 rounded-full ${DIAGNOSIS_STYLE[t].dot}`} />
                  <span className="font-semibold tabular-nums">{summary[t]}</span>
                  <span className="text-[var(--text-2)]">
                    {t === "visible" ? "visible" : t.replace("_", " ")}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Query × engine matrix with diagnosis */}
          <section className="card p-4">
            <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
              Who appears in each answer
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-[var(--text-2)]">
                  <tr>
                    <th className="py-2 pr-4">Question</th>
                    {surfaces.map((s) => (
                      <th key={s} className="px-2 text-center text-xs">
                        <span className="inline-flex flex-col items-center gap-1">
                          <EngineMark surface={s} size={18} />
                          {surfaceLabel(s)}
                        </span>
                      </th>
                    ))}
                    <th className="pl-4">Diagnosis</th>
                    <th className="pl-4">Fix</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {matrix.map((row) => (
                    <tr key={row.id} className="border-t border-[var(--border)] align-top">
                      <td className="max-w-xs py-3 pr-4 font-medium">{row.query}</td>
                      {surfaces.map((s) => {
                        const cell = row.cells[s];
                        return (
                          <td key={s} className="px-2 py-3 text-center">
                            <span
                              title={cell?.competitors?.length ? cell.competitors.join(", ") : ""}
                              className={`inline-block min-w-12 rounded px-2 py-0.5 text-xs ${
                                CELL_STYLE[cell?.state ?? "absent"]
                              }`}
                            >
                              {CELL_LABEL[cell?.state ?? "absent"]}
                            </span>
                          </td>
                        );
                      })}
                      <td className="whitespace-nowrap py-3 pl-4">
                        <div className={`flex items-center gap-1.5 text-xs font-medium ${(DIAGNOSIS_STYLE[row.diagnosis.type] ?? DIAGNOSIS_STYLE.undetermined).chip}`}>
                          <span className={`h-2 w-2 rounded-full ${(DIAGNOSIS_STYLE[row.diagnosis.type] ?? DIAGNOSIS_STYLE.undetermined).dot}`} />
                          {row.diagnosis.label}
                        </div>
                      </td>
                      <td className="max-w-md py-3 pl-4 text-xs text-[var(--text-2)]">
                        {row.diagnosis.type !== "visible" && <Linkify text={row.diagnosis.fix} />}
                      </td>
                      <td className="py-2.5 pl-3">
                        {row.diagnosis.type !== "visible" && (
                          <AddToPlan
                            gapRef={`matrix:${row.id}`}
                            title={`Win “${short(row.query)}”`}
                            actionText={row.diagnosis.fix}
                            link="/dashboard/engines"
                            queryText={row.query}
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      {ads.data && <AdsSection d={ads.data} />}
    </main>
  );
}
