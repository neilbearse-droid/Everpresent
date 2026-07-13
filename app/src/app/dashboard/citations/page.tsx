import { apiFetch, type CitationsPayload, type Me } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { AIOTile } from "@/components/aio-tile";

const CATEGORY_STYLES: Record<string, string> = {
  brand: "bg-emerald-700 text-white",
  competitor: "bg-amber-700 text-white",
  other: "bg-slate-700 text-slate-200",
};

export default async function CitationsPage() {
  const [me, payload] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<CitationsPayload>("/api/tenant/citations-intel"),
  ]);
  const data = payload.data;

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active="Citations" isSuperadmin={me.data?.is_superadmin} />

      {!data ? (
        <p className="text-sm text-slate-400">{payload.error}</p>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2">
            <AIOTile aio={data.aio} />
            <div className="rounded-lg border border-slate-700 bg-slate-900 p-5">
              <div className="text-3xl font-semibold tabular-nums">
                {data.domains.filter((d) => d.category === "brand").length > 0 ? "Yes" : "No"}
              </div>
              <div className="mt-1 text-sm text-slate-400">
                Your domains appear among the sources AI answers cite
              </div>
            </div>
          </div>

          <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
            <h2 className="mb-1 text-sm font-medium text-slate-400">
              Domains AI answers cite in this vertical
            </h2>
            <p className="mb-4 text-xs text-slate-500">
              Across all measured surfaces, including Google's AI Overview. Getting your
              brand into these sources is how you enter the answers.
            </p>
            {data.domains.length === 0 ? (
              <p className="text-sm text-slate-500">No citations captured yet.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="text-slate-400">
                  <tr>
                    <th className="py-2 pr-4">Domain</th>
                    <th className="pr-4">Category</th>
                    <th className="pr-4">Citations</th>
                    <th>Surfaces</th>
                  </tr>
                </thead>
                <tbody>
                  {data.domains.map((d) => (
                    <tr key={d.domain} className="border-t border-slate-800">
                      <td className="py-2.5 pr-4 font-medium">{d.domain}</td>
                      <td className="pr-4">
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-medium ${
                            CATEGORY_STYLES[d.category] ?? CATEGORY_STYLES.other
                          }`}
                        >
                          {d.category || "other"}
                        </span>
                      </td>
                      <td className="pr-4 tabular-nums">{d.count}</td>
                      <td className="font-mono text-xs text-slate-400">
                        {d.surfaces.join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </main>
  );
}
