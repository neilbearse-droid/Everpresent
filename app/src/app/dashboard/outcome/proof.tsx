import Link from "next/link";
import type { PageChangeRow, Proof, ProofItem, ProofSignal } from "@/lib/api";
import { AREA_LABEL, BAND_LABEL } from "@/lib/recs";
import { Delta, ExtLink, Linkify, shortUrl } from "@/components/ui";
import { removeFix } from "./actions";

const STATUS: Record<ProofItem["status"], string> = {
  proven: "Real lift",
  early: "Early signal",
  no_change: "No change yet",
  worse: "Down",
  awaiting: "Measuring",
  confounded: "Confounded",
};
// A wrong fact is fixed when it is said less often: "Real lift" would misread.
const STATUS_LOWER: Partial<Record<ProofItem["status"], string>> = {
  proven: "Real drop",
  worse: "Up",
};

function signed(n: number | null | undefined, unit: string) {
  if (n === null || n === undefined) return "—";
  return `${n > 0 ? "+" : ""}${n}${unit}`;
}

function SignalRow({ s }: { s: ProofSignal }) {
  const rate = s.kind === "rate";
  const before = s.before === null ? "—" : rate ? `${s.before}%` : s.before.toLocaleString();
  const after = s.after === null ? "—" : rate ? `${s.after}%` : s.after.toLocaleString();
  const change = rate ? <Delta value={s.delta_pts} unit=" pts" /> : <Delta value={s.change_pct} unit="%" />;
  const control = rate
    ? signed(s.control_delta_pts, " pts")
    : s.kind === "count"
      ? signed(s.control_change_pct, "%")
      : "n/a";
  const lower = Boolean(s.lower_is_better);
  const bad = lower ? s.verdict === "up" : s.verdict === "down" || s.verdict === "down vs control";
  const good = lower ? s.verdict === "down" : s.verdict === "up" || s.verdict === "up vs control";
  return (
    <tr>
      <td>
        <span className="font-semibold">{s.label}</span>
        <span className="block text-[11px] text-[var(--text-3)]">{s.note}</span>
      </td>
      <td className="tabular-nums">
        {before} → {after}
        {rate && (
          <span className="block text-[11px] text-[var(--text-3)]">
            {s.before_n} → {s.after_n} answers
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

function statusLabel(it: ProofItem) {
  return (it.metric === "wrong_fact" && STATUS_LOWER[it.status]) || STATUS[it.status];
}

/** One fix as an experiment: what it was, what it predicted, what happened. */
function FixCard({ it }: { it: ProofItem }) {
  const detected = it.source === "detected";
  const facts = [
    detected ? "Seen by the crawl; nobody logged it" : "Logged",
    AREA_LABEL[it.category],
    it.predicted?.band ? `Predicted: ${BAND_LABEL[it.predicted.band].toLowerCase()}` : "",
    it.status === "proven" && it.days_to_effect ? `Showed within ${it.days_to_effect} days` : "",
  ].filter(Boolean);
  return (
    <div className="border-t border-[var(--line)] first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 pt-4">
        <div>
          {/* Bad news is an ink pill, never the brand colour. */}
          <span
            className={`mr-2 text-xs font-semibold ${
              it.status === "confounded" ? "bp-neg" : "text-[var(--text-3)]"
            }`}
          >
            {statusLabel(it)}
          </span>
          <span className="text-[14px] font-semibold">{it.description || it.query}</span>
        </div>
        <span className="text-xs text-[var(--text-3)]">
          {detected ? "changed around" : "shipped"} {it.shipped_at}
          {it.url ? (
            <>
              {" · "}
              <ExtLink href={it.url}>{it.path || "fix"}</ExtLink>
            </>
          ) : (
            it.path && <span className="font-mono"> · {it.path}</span>
          )}
        </span>
      </div>
      <p className="px-4 pt-1 text-[12px] text-[var(--text-3)]">{facts.join(" · ")}</p>
      <p className="px-4 pb-2 pt-1 text-[13px] text-[var(--text-2)]">
        <Linkify text={it.headline} />
      </p>
      {it.changes.length > 0 && (
        <p className="px-4 pb-2 text-[12.5px] text-[var(--text-2)]">
          <span className="font-semibold text-[var(--text)]">Seen on the page:</span>{" "}
          {it.changes.map((c) => c.summary).join("; ")}.
        </p>
      )}
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
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-2">
        {it.by_engine.length > 1 ? (
          <details className="text-[12.5px] text-[var(--text-2)]">
            <summary className="cursor-pointer text-[var(--text-3)] hover:text-[var(--text-2)]">
              By engine
            </summary>
            <ul className="mt-1.5 space-y-0.5">
              {it.by_engine.map((e) => (
                <li key={e.family} className="tabular-nums">
                  <span className="inline-block w-44 font-medium text-[var(--text)]">{e.label}</span>
                  {e.before ?? "—"}% → {e.after ?? "—"}%
                  <span className="ml-2 text-[var(--text-3)]">
                    ({e.before_n} → {e.after_n} answers; {e.verdict})
                  </span>
                </li>
              ))}
            </ul>
          </details>
        ) : (
          <span />
        )}
        <form action={removeFix.bind(null, it.id)}>
          <button
            className="text-[12px] text-[var(--text-3)] underline-offset-2 hover:text-[var(--text)] hover:underline"
            title={detected ? "Not a real edit? Remove it from the list." : "Logged by mistake? Remove it."}
          >
            Remove
          </button>
        </form>
      </div>
    </div>
  );
}

/** A rival's page changed: the same test, on that rival's mentions. */
function RivalRow({ it }: { it: ProofItem }) {
  const s = it.signals[0];
  return (
    <li className="border-t border-[var(--line)] px-4 py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[13.5px]">
          <span className="chip mr-2 align-middle">{it.subject}</span>
          <span className="font-semibold">{it.description}</span>
        </p>
        <span className="text-xs text-[var(--text-3)]">
          around {it.shipped_at}
          {it.url && (
            <>
              {" · "}
              <ExtLink href={it.url}>{shortUrl(it.url, 36)}</ExtLink>
            </>
          )}
        </span>
      </div>
      <p className="mt-1 text-[13px] text-[var(--text-2)]">
        <span className="mr-2 text-xs font-semibold text-[var(--text-3)]">{STATUS[it.status]}</span>
        <Linkify text={it.headline} />
      </p>
      {s && s.before !== null && s.after !== null && (
        <p className="mt-0.5 text-[12px] tabular-nums text-[var(--text-3)]">
          {s.label}: {s.before}% → {s.after}% ({s.before_n} → {s.after_n} answers; {s.note})
        </p>
      )}
    </li>
  );
}

function ChangesTable({ rows }: { rows: PageChangeRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="bp-table w-full min-w-[640px]">
        <thead>
          <tr>
            <th>Seen between</th>
            <th>Whose page</th>
            <th>Page</th>
            <th>What changed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td className="whitespace-nowrap tabular-nums text-[var(--text-2)]">
                {c.between[0]} → {c.between[1]}
              </td>
              <td className="whitespace-nowrap">{c.owner_label}</td>
              <td>
                <ExtLink href={c.url}>{shortUrl(c.url, 40)}</ExtLink>
              </td>
              <td>
                {c.summaries.join("; ")}
                {c.intervention_id !== null && (
                  <span className="ml-2 whitespace-nowrap text-[11px] text-[var(--text-3)]">
                    measured above
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Each fix, logged or detected: before vs after, against a control. Then
 * what rivals changed, and every change the crawl has seen on cited pages. */
export function ProofSection({ p }: { p: Proof }) {
  const rivals = p.rival_items ?? [];
  const changes = p.changes ?? [];
  return (
    <>
      <section className="blueprint mb-6 grid-cols-1">
        <div>
          <div className="bp-bar">
            <span>Proof: fixes, before and after</span>
            <span>{p.window_days} days either side of each date</span>
          </div>
          {p.items.length === 0 ? (
            <p className="p-4 text-sm text-[var(--text-2)]">
              No fixes recorded yet.{" "}
              <Link href="/dashboard/recommendations" className="bp-link">
                Mark a recommendation done to start measuring →
              </Link>
            </p>
          ) : (
            <>
              {p.summary && (
                <p className="px-4 pt-3 text-[13px] text-[var(--text-2)]">
                  <Linkify text={p.summary} />
                </p>
              )}
              {p.items.map((it) => (
                <FixCard key={it.id} it={it} />
              ))}
            </>
          )}
        </div>
      </section>

      {rivals.length > 0 && (
        <section className="blueprint mb-6 grid-cols-1">
          <div>
            <div className="bp-bar">
              <span>What rivals changed, and what it did for them</span>
              <span>Their pages, their mention rates</span>
            </div>
            <ul>
              {rivals.map((it) => (
                <RivalRow key={it.id} it={it} />
              ))}
            </ul>
          </div>
        </section>
      )}

      {changes.length > 0 && (
        <section className="blueprint mb-6 grid-cols-1">
          <div>
            <div className="bp-bar">
              <span>Changes seen on cited pages</span>
              <span>Last 60 days, from the page crawl</span>
            </div>
            <ChangesTable rows={changes} />
          </div>
        </section>
      )}
    </>
  );
}
