import Link from "next/link";
import type { Briefing } from "@/lib/api";

const VERDICT: Record<Briefing["winning"]["verdict"], string> = {
  gaining: "Gaining",
  losing: "Losing ground",
  holding: "Holding",
  unknown: "Not measured yet",
};

/** The weekly briefing: are we winning, why, and what to do this week. */
export function BriefingBlock({ b }: { b: Briefing }) {
  const v = b.winning.verdict;
  return (
    <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-3">
      <div className="p-5">
        <div className="bp-label mb-2">Are we winning?</div>
        <span
          className={
            v === "losing"
              ? "bp-neg"
              : v === "gaining"
                ? "font-semibold text-[var(--accent-display)]"
                : "font-semibold"
          }
        >
          {VERDICT[v]}
        </span>
        <p className="mt-2 text-[13px] leading-relaxed text-[var(--text-2)]">{b.winning.line}</p>
        {b.focus && (
          <p className="mt-3 text-xs text-[var(--text-3)]">
            Focus: <span className="text-[var(--text-2)]">{b.focus}</span>
          </p>
        )}
      </div>
      <div className="p-5">
        <div className="bp-label mb-2">Why</div>
        {b.why.length === 0 ? (
          <p className="text-[13px] text-[var(--text-2)]">Nothing unusual in the data this week.</p>
        ) : (
          <ul className="space-y-2">
            {b.why.map((r, i) => (
              <li key={i} className="text-[13px] leading-relaxed text-[var(--text-2)]">
                {r.text}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="p-5">
        <div className="bp-label mb-2">This week</div>
        {b.this_week.length === 0 ? (
          <p className="text-[13px] text-[var(--text-2)]">No open plays. Nice.</p>
        ) : (
          <ol className="list-decimal space-y-2 pl-4">
            {b.this_week.map((p) => (
              <li key={p.id} className="text-[13px] leading-relaxed">
                <Link href="/dashboard/recommendations" className="hover:underline">
                  {p.title}
                </Link>
                {p.why && (
                  <span className="line-clamp-2 block text-xs text-[var(--text-3)]">{p.why}</span>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
