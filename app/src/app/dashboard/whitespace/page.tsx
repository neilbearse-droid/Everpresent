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
    <main className="mx-auto max-w-[1400px] px-6 pb-16">
      <DashNav active="Whitespace" isSuperadmin={me.data?.is_superadmin} withDateRange />

      <div className="mb-6">
        <p className="eyebrow mb-1.5">Category opportunity</p>
        <h1 className="text-[26px] font-semibold tracking-tight">Who else the AI recommends</h1>
        <p className="mt-2 max-w-3xl text-sm text-[var(--text-2)]">
          Products and companies the AI recommends that aren&apos;t on your tracked list. When an
          answer names none of your brand or tracked competitors, it points to a category where
          you aren&apos;t visible.
        </p>
      </div>

      {!data?.observed ? (
        <section className="card p-4">
          <h2 className="mb-2 text-lg font-medium">No out-of-list mentions yet</h2>
          <p className="text-sm text-[var(--text-2)]">
            {data && data.measured > 0
              ? "The tracked brand and competitors account for every name the answers surfaced in this range."
              : "No data yet. Untracked names appear here once entity extraction is enabled for this account."}
          </p>
        </section>
      ) : (
        <section className="card p-4">
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
