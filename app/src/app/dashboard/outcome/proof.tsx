import Link from "next/link";
import type { Proof, ProofSignal } from "@/lib/api";

const STATUS: Record<Proof["items"][number]["status"], string> = {
  proven: "Real lift",
  early: "Early signal",
  no_change: "No change yet",
  worse: "Down",
  awaiting: "Measuring",
};

function signed(n: number | null | undefined, unit: string) {
  if (n === null || n === undefined) return "—";
  return `${n > 0 ? "+" : ""}${n}${unit}`;
}

function SignalRow({ s }: { s: ProofSignal }) {
  const rate = s.kind === "rate";
  const before = s.before === null ? "—" : rate ? `${s.before}%` : s.before.toLocaleString();
  const after = s.after === null ? "—" : rate ? `${s.after}%` : s.after.toLocaleString();
  const change = rate ? signed(s.delta_pts, " pts") : signed(s.change_pct, "%");
  const control = rate
    ? signed(s.control_delta_pts, " pts")
    : s.kind === "count"
      ? signed(s.control_change_pct, "%")
      : "n/a";
  const bad = s.verdict === "down" || s.verdict === "down vs control";
  const good = s.verdict === "up" || s.verdict === "up vs control";
  return (
    <tr>
      <td>
        {s.label}
        <span className="block text-[11px] text-[var(--text-3)]">{s.note}</span>
      </td>
      <td className="tabular-nums">
        {before} → {after}
        {rate && (
          <span className="block text-[11px] text-[var(--text-3)]">
            n={s.before_n} → {s.after_n}
          </span>
        )}
      </td>
      <td className="tabular-nums">{change}</td>
      <td className="tabular-nums text-[var(--text-2)]">{control}</td>
      <td>
        {bad ? (
          <span className="bp-neg">{s.verdict}</span>
        ) : (
          <span className={good ? "font-semibold text-[var(--accent-display)]" : "text-[var(--text-2)]"}>
            {s.verdict}
          </span>
        )}
      </td>
    </tr>
  );
}

/** Each shipped fix: before vs after, against a control, on every signal. */
export function ProofSection({ p }: { p: Proof }) {
  return (
    <section className="blueprint mb-6 grid-cols-1">
      <div>
        <div className="bp-bar">
          <span>Proof: did the fixes work?</span>
          <span>{p.window_days} days either side of each ship date</span>
        </div>
        {p.items.length === 0 ? (
          <p className="p-4 text-sm text-[var(--text-2)]">
            Log a fix when you ship it (on the{" "}
            <Link href="/dashboard/action-plan" className="underline">
              Action Plan
            </Link>
            ) and this compares the weeks before and after it with the questions and pages you
            didn&apos;t touch.
          </p>
        ) : (
          <>
            {p.summary && <p className="px-4 pt-3 text-[13px] text-[var(--text-2)]">{p.summary}</p>}
            {p.items.map((it) => (
              <div key={it.id} className="border-t border-[var(--line)] first:border-t-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 pt-4">
                  <div>
                    <span className="mr-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-3)]">
                      {STATUS[it.status]}
                    </span>
                    <span className="text-[14px] font-semibold">{it.description || it.query}</span>
                  </div>
                  <span className="text-xs text-[var(--text-3)]">
                    shipped {it.shipped_at}
                    {it.path && ` · ${it.path}`}
                  </span>
                </div>
                <p className="px-4 pb-2 text-[13px] text-[var(--text-2)]">{it.headline}</p>
                <div className="overflow-x-auto">
                  <table className="bp-table w-full min-w-[640px]">
                    <thead>
                      <tr>
                        <th>Signal</th>
                        <th>Before → after</th>
                        <th>Change</th>
                        <th>Control</th>
                        <th>Verdict</th>
                      </tr>
                    </thead>
                    <tbody>
                      {it.signals.map((s) => (
                        <SignalRow key={s.key} s={s} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
            <p className="px-4 pb-3 pt-2 text-xs text-[var(--text-3)]">
              Only the answer change is tested for significance. Bot reads and search impressions
              are directional counts; AI referrals are sitewide and shown as context, not proof.
            </p>
          </>
        )}
      </div>
    </section>
  );
}
