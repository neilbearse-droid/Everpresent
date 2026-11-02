import { apiFetch, rangeQuery, type Me, type WhitespaceReport } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";

export default async function WhitespacePage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const { from, to } = await searchParams;
  const [me, report] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<WhitespaceReport>(`/api/tenant/whitespace${rangeQuery(from, to)}`),
  ]);
  if (report.status === 403) {
    return (
      <NoOrgNotice active="Untracked rivals" isSuperadmin={me.data?.is_superadmin} detail={report.error} />
    );
  }
  const data = report.data;

  // The lead: who else the engines recommend, and whether to start tracking them.
  const top = data?.observed ? [...data.entities].sort((a, b) => b.count - a.count)[0] : null;
  const lead = !data?.observed
    ? data && data.measured > 0
      ? {
          tells: `Every name in ${data.measured} answers is ${data.brand_name} or a competitor you already track. Nobody is slipping into these answers unnoticed.`,
          act: "Nothing to add. Check back after a few runs; new names appear here first.",
          tone: "good" as const,
        }
      : {
          tells: "No data yet. This page lists the products and companies AI answers recommend that are neither you nor a competitor you track.",
          act: "Nothing to do until name detection is turned on for this account and a run has finished.",
          tone: "neutral" as const,
        }
    : {
        tells: (
          <>
            {data.entity_count} {data.entity_count === 1 ? "name" : "names"} you don&apos;t track appear
            across {data.measured} answers. {top!.name} is the most common, named {top!.count}{" "}
            {top!.count === 1 ? "time" : "times"}
            {top!.engines.length > 0 && <> on {top!.engines.join(", ")}</>}.
          </>
        ),
        act: `If ${top!.name} competes with you, have it added to your tracked competitors so share of voice and head-to-head count it. If it doesn't, it marks a part of the category the engines think you're not in; the questions it appears on are the ones to cover.`,
        href: "/dashboard/queries",
        hrefLabel: "Queries",
        tone: "neutral" as const,
      };

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Untracked rivals" isSuperadmin={me.data?.is_superadmin} withDateRange />
      <PageLead {...lead} />

      {!data?.observed ? (
        <section className="card p-4">
          <h2 className="mb-2 text-lg font-medium">No untracked names yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            {data && data.measured > 0
              ? "Every name in this date range's answers is your brand or a tracked competitor."
              : "No data yet. Untracked names appear here once name detection is turned on for this account."}
          </p>
        </section>
      ) : (
        <section className="card p-4">
          <h2 className="mb-1 text-sm font-medium text-[var(--text-2)]">
            Who else the AI recommends
          </h2>
          <p className="mb-4 max-w-3xl text-xs text-[var(--text-3)]">
            Products and companies named in AI answers that aren&apos;t you or a tracked
            competitor, most often first. {data.entity_count} distinct across {data.measured} answers.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--text-3)]">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-4 font-medium tabular-nums">Mentions</th>
                  <th className="pb-2 pr-4 font-medium">Personas</th>
                  <th className="pb-2 font-medium">Engines</th>
                </tr>
              </thead>
              <tbody>
                {data.entities.map((e) => (
                  <tr key={e.name} className="border-t border-[var(--border)] align-top">
                    <td className="py-2.5 pr-4 font-medium text-[var(--text)]">{e.name}</td>
                    <td className="py-2.5 pr-4 tabular-nums text-[var(--text-2)]">{e.count}</td>
                    <td className="py-2.5 pr-4 text-xs text-[var(--text-2)]">
                      {e.segments.join(", ")}
                    </td>
                    <td className="py-2.5 text-xs text-[var(--text-2)]">{e.engines.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
