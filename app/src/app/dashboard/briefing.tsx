import Link from "next/link";
import type { Briefing } from "@/lib/api";

const VERDICT: Record<Briefing["winning"]["verdict"], string> = {
  gaining: "Gaining",
  losing: "Losing ground",
  holding: "Holding steady",
  baseline: "Building baseline",
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
          className={`pill ${v === "losing" ? "pill-bad" : v === "gaining" ? "pill-good" : ""}`}
        >
          {VERDICT[v]}
        </span>
        <p className="mt-2 text-[13px] leading-relaxed text-[var(--text-2)]">
          {b.winning.line}
        </p>
        {b.focus && (
          <p className="mt-3 text-xs text-[var(--text-3)]">
            Focus: <span className="text-[var(--text-2)]">{b.focus}</span>
          </p>
        )}
      </div>
      <div className="p-5">
        <div className="bp-label mb-2">Why</div>
        {b.why.length === 0 ? (
          <p className="text-[13px] text-[var(--text-2)]">
            Nothing unusual in the data this week.
          </p>
        ) : (
          <ul className="space-y-2">
            {b.why.map((r, i) => (
              <li
                key={i}
                className="text-[13px] leading-relaxed text-[var(--text-2)]"
              >
                {r.text}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="p-5">
        <div className="bp-label mb-2">This week</div>
        {b.this_week.length === 0 ? (
          <p className="text-[13px] text-[var(--text-2)]">
            No open plays. Nice.
          </p>
        ) : (
          <ol className="space-y-3">
            {b.this_week.map((p, i) => (
              <li key={p.id} className="flex gap-3 text-[13px] leading-relaxed">
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[var(--plane-2)] text-[11px] font-semibold tabular-nums text-[var(--text-2)]">
                  {i + 1}
                </span>
                <span className="min-w-0">
                  <Link
                    href="/dashboard/recommendations"
                    className="font-semibold hover:underline"
                  >
                    {p.title}
                  </Link>
                  {p.why && (
                    <span className="line-clamp-2 block text-xs text-[var(--text-3)]">
                      {p.why}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
