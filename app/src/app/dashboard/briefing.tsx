import Link from "next/link";
import type { Briefing, OverviewPayload } from "@/lib/api";

type Alert = NonNullable<OverviewPayload["alerts"]>[number];

/**
 * The weekly briefing, under the headline number: why it is what it is, and
 * what to do this week. "Where you stand" is the hero above, so it is not
 * repeated here. Alerts ("what changed") belong with the reasons.
 */
export function BriefingBlock({ b, alerts = [] }: { b: Briefing; alerts?: Alert[] }) {
  return (
    <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-2">
      <div>
        <div className="bp-bar">
          <span>Why</span>
          {alerts.length > 0 && <span>{alerts.length} changed</span>}
        </div>
        <div className="p-5">
          {b.why.length === 0 && alerts.length === 0 ? (
            <p className="text-[13px] text-[var(--text-2)]">
              Nothing unusual.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {b.why.slice(0, 3).map((r, i) => (
                <li key={`why-${i}`} className="text-[13.5px] leading-relaxed text-[var(--text)]">
                  {r.text}
                </li>
              ))}
              {alerts.map((a, i) => (
                <li key={`alert-${i}`} className="flex items-start gap-3 text-[13px] leading-relaxed">
                  <span
                    className={`bp-label mt-0.5 shrink-0 px-1.5 ${
                      a.severity === "high" ? "bp-neg" : a.severity === "good" ? "bp-mark" : ""
                    }`}
                  >
                    {a.severity === "high" ? "Act" : a.severity === "good" ? "Win" : "Watch"}
                  </span>
                  <span className="text-[var(--text-2)]">{a.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div>
        <div className="bp-bar">
          <span>This week</span>
          <Link href="/dashboard/recommendations" className="hover:underline">
            All recommendations →
          </Link>
        </div>
        <div className="p-5">
          {b.this_week.length === 0 ? (
            <p className="text-[13px] text-[var(--text-2)]">
              No open recommendations.
            </p>
          ) : (
            <ol className="space-y-3.5">
              {b.this_week.slice(0, 3).map((p, i) => (
                <li key={p.id} className="flex gap-3 text-[13.5px] leading-relaxed">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--plane-2)] text-[11.5px] font-semibold tabular-nums text-[var(--text-2)]">
                    {i + 1}
                  </span>
                  <span className="min-w-0">
                    <Link href={p.link || "/dashboard/recommendations"} className="font-semibold hover:underline">
                      {p.title}
                    </Link>
                    {p.why && (
                      <span className="line-clamp-2 block text-[12.5px] text-[var(--text-3)]">
                        {p.why}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
