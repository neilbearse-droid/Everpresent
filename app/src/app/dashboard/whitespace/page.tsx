import { apiFetch, rangeQuery, type Me, type WhitespaceReport } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";

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
      <NoOrgNotice active="Whitespace" isSuperadmin={me.data?.is_superadmin} detail={report.error} />
    );
  }
  const data = report.data;

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Whitespace" isSuperadmin={me.data?.is_superadmin} withDateRange />

      <div className="mb-6">
        <p className="eyebrow mb-1.5">Category opportunity</p>
        <h1 className="text-[26px] font-semibold tracking-tight">Who else the AI recommends</h1>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-2)]">
          Products and companies the AI names as options that aren&apos;t on your tracked list —
          the whitespace. When the assistant answers a persona and none of the names it returns is
          yours or a tracked rival, that&apos;s a category you&apos;re invisible in.
        </p>
      </div>

      {!data?.observed ? (
        <section className="card p-6">
          <h2 className="mb-2 text-lg font-medium">No out-of-list mentions yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            {data && data.measured > 0
              ? "The tracked brand and competitors account for every name the answers surfaced in this range."
              : "Enable entity extraction for this tenant and run a collection — untracked names appear here after processing."}
          </p>
        </section>
      ) : (
        <section className="card p-6">
          <h2 className="mb-4 text-sm font-medium text-[var(--text-2)]">
            Untracked names across {data.measured} answers · {data.entity_count} distinct
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--text-3)]">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-4 font-medium tabular-nums">Mentions</th>
                  <th className="pb-2 pr-4 font-medium">Surfaced to</th>
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
