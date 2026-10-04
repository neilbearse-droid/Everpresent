import type { AdsReport } from "@/lib/api";

/** Paid units next to AI answers. Never part of organic share. */
export function AdsSection({ d }: { d: AdsReport }) {
  return (
    <section className="blueprint mt-6 grid-cols-1 lg:grid-cols-2">
      <div>
        <div className="bp-bar">
          <span>Sponsored units next to answers</span>
          <span>last {d.days} days</span>
        </div>
        {!d.has_data ? (
          <p className="p-4 text-sm text-[var(--text-2)]">
            No sponsored units seen in {d.answers.toLocaleString()} answers. When an engine shows a
            paid unit, it is cut from the answer before anything is counted and listed here instead.
          </p>
        ) : (
          <table className="bp-table w-full">
            <thead>
              <tr>
                <th>Engine</th>
                <th>Answers with an ad</th>
              </tr>
            </thead>
            <tbody>
              {d.engines.map((e) => (
                <tr key={e.surface}>
                  <td>{e.label}</td>
                  <td className="tabular-nums">
                    {e.ad_rate}%
                    <span className="ml-1 text-xs text-[var(--text-3)]">
                      {e.with_ads} of {e.answers}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div>
        <div className="bp-bar">
          <span>Who advertises</span>
          <span>{d.has_data ? `${d.brand} ${d.brand_share}% of units` : ""}</span>
        </div>
        {d.has_data ? (
          <ul>
            {d.advertisers.map((a) => (
              <li key={a.name} className="border-t border-[var(--line)] px-4 py-2.5 first:border-t-0">
                <div className="flex justify-between text-[13px]">
                  <span className={a.type === "brand" ? "font-semibold" : ""}>{a.name}</span>
                  <span className="tabular-nums">
                    {a.share}% <span className="text-xs text-[var(--text-3)]">· {a.units}</span>
                  </span>
                </div>
                {a.example && <p className="truncate text-xs text-[var(--text-3)]">{a.example}</p>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-4 text-sm text-[var(--text-2)]">Nothing yet.</p>
        )}
        <p className="px-4 pb-3 pt-2 text-xs text-[var(--text-3)]">
          Paid units are kept out of mention rates, share of voice and citations. Browser engines
          run signed out, so this shows the ads a logged-out visitor sees.
        </p>
      </div>
    </section>
  );
}
