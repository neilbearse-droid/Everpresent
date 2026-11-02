import Link from "next/link";
import type { Briefing, OverviewPayload } from "@/lib/api";
import { Bullets, type Tone } from "@/components/ui";
import { StatusButtons } from "@/components/plan-buttons";

type Alert = NonNullable<OverviewPayload["alerts"]>[number];

const KIND: Record<string, string> = {
  accuracy: "Wrong fact",
  refresh: "Lost citation",
  own_page: "Your page",
  subquery: "Sub-question",
  web_search: "Search gap",
  crawler_access: "Bot access",
  broken_page: "Broken page",
  strategy: "Focus",
  earned: "Earned media",
  owned: "Your site",
  training: "Model memory",
  aio: "AI Overview",
  read_not_cited: "Read, not cited",
};

function tone(t: string): Tone {
  return t === "high" || t === "bad" ? "bad" : t === "good" ? "good" : "neutral";
}

/** Why, and this week: bullets with a lead-in on the left; the top three
 * recommendations with their buttons on the right. */
export function BriefingBlock({ b, alerts = [] }: { b: Briefing; alerts?: Alert[] }) {
  const why = [
    ...b.why.slice(0, 4).map((r) => ({ text: r.text, tone: tone(r.tone) })),
    ...alerts.slice(0, 2).map((a) => ({ text: a.text, tone: tone(a.severity) })),
  ].slice(0, 5);
  return (
    <section className="blueprint mb-6 grid-cols-1 lg:grid-cols-5">
      <div className="lg:col-span-2">
        <div className="bp-bar">
          <span>Why</span>
        </div>
        <div className="p-5">
          {why.length === 0 ? (
            <p className="text-[13px] text-[var(--text-2)]">Nothing unusual.</p>
          ) : (
            <Bullets items={why} />
          )}
        </div>
      </div>
      <div className="lg:col-span-3">
        <div className="bp-bar">
          <span>This week</span>
          <Link href="/dashboard/recommendations" className="hover:underline">
            All recommendations →
          </Link>
        </div>
        {b.this_week.length === 0 ? (
          <p className="p-5 text-[13px] text-[var(--text-2)]">No open recommendations.</p>
        ) : (
          <ol>
            {b.this_week.slice(0, 3).map((p, i) => (
              <li
                key={p.id}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[var(--line)] px-5 py-3 first:border-t-0"
              >
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--plane-2)] text-[11.5px] font-semibold tabular-nums text-[var(--text-2)]">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="chip mr-2 align-middle">{KIND[p.kind] ?? p.kind}</span>
                  <Link href={p.link || "/dashboard/recommendations"} className="align-middle text-[14px] font-semibold hover:underline">
                    {p.title}
                  </Link>
                </span>
                <StatusButtons id={p.id} status={p.status} compact />
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
