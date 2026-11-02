import { apiFetch, rangeQuery, type Me, type WhitespaceReport } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { PageLead } from "@/components/page-lead";
import { EngineMark } from "@/components/ui";
import { AddToPlan } from "@/components/plan-buttons";

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
          tells: `No untracked names in ${data.measured} answers.`,
          act: "Nothing to add.",
          tone: "good" as const,
        }
      : {
          tells: "No data yet.",
          act: "Nothing to do yet.",
          tone: "neutral" as const,
        }
    : {
        tells: (
          <>
            {data.entity_count} untracked {data.entity_count === 1 ? "name appears" : "names appear"} in your answers;{" "}
            {top!.name} most, {top!.count} {top!.count === 1 ? "time" : "times"}.
          </>
        ),
        act: `Track ${top!.name} if it competes with you; otherwise cover its questions.`,
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
          <p className="text-sm text-[var(--text-2)]">
            {data && data.measured > 0 ? "No untracked names in this range." : "No data yet."}
          </p>
        </section>
      ) : (
        <section className="card p-4">
          <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
            Untracked names · <span className="font-semibold text-[var(--text)]">{data.entity_count}</span> in {data.measured} answers
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--text-3)]">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-4 font-medium tabular-nums">Mentions</th>
                  <th className="pb-2 pr-4 font-medium">Personas</th>
                  <th className="pb-2 pr-4 font-medium">Engines</th>
                  <th className="pb-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {data.entities.map((e) => (
                  <tr key={e.name} className="border-t border-[var(--border)] align-top">
                    <td className="py-2.5 pr-4 font-semibold text-[var(--text)]">{e.name}</td>
                    <td className="py-2.5 pr-4 font-semibold tabular-nums">{e.count}</td>
                    <td className="py-2.5 pr-4 text-xs text-[var(--text-2)]">
                      {e.segments.join(", ")}
                    </td>
                    <td className="py-2.5 pr-4 text-xs text-[var(--text-2)]">
                      <span className="flex flex-wrap items-center gap-1.5">
                        {e.engines.map((en) => (
                          <span key={en} className="inline-flex items-center gap-1">
                            <EngineMark surface={en} size={14} />
                            {en}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td className="py-2.5">
                      <AddToPlan
                        gapRef={`track:${e.name}`}
                        title={`Track ${e.name}`}
                        actionText={`${e.name} appears in ${e.count} of your answers (${e.engines.join(", ")}) and isn't a tracked competitor. Add it, or cover the questions it appears on.`}
                        link="/dashboard/whitespace"
                      />
                    </td>
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
