import {
  addToPlan,
  markRecommendationDone,
  setRecommendationStatus,
} from "@/app/dashboard/recommendations/actions";

/** Start / Mark done / Dismiss for a recommendation that already exists.
 * `withoutDone` leaves "Mark done" to a DoneForm beside it, which records
 * what changed; without it, the plain button still logs the fix with
 * today's date. */
export function StatusButtons({
  id,
  status,
  compact = false,
  withoutDone = false,
}: {
  id: number;
  status: string;
  compact?: boolean;
  withoutDone?: boolean;
}) {
  const btn = `btn whitespace-nowrap ${compact ? "px-2.5 py-1 text-[12px]" : "px-3 py-1.5 text-xs"}`;
  const all: { to: string; label: string; primary?: boolean }[] =
    status === "open"
      ? [{ to: "in_progress", label: "Start", primary: true }, { to: "dismissed", label: "Dismiss" }]
      : status === "in_progress"
        ? [{ to: "done", label: "Mark done", primary: true }, { to: "open", label: "Stop" }]
        : [{ to: "open", label: "Reopen" }];
  const next = withoutDone ? all.filter((n) => n.to !== "done") : all;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {next.map((n) => (
        <form key={n.to} action={setRecommendationStatus.bind(null, id, n.to)}>
          <button className={`${btn} ${n.primary ? "btn-primary" : "btn-ghost"}`}>{n.label}</button>
        </form>
      ))}
    </span>
  );
}

/** "Add to plan" for an action that is not yet a recommendation. */
export function AddToPlan({
  gapRef,
  title,
  actionText,
  link,
  queryText,
  compact = true,
}: {
  gapRef: string;
  title: string;
  actionText?: string;
  link?: string;
  queryText?: string;
  compact?: boolean;
}) {
  return (
    <form action={addToPlan.bind(null, { gapRef, title, actionText, link, queryText })}>
      <button className={`btn btn-ghost whitespace-nowrap ${compact ? "px-2.5 py-1 text-[12px]" : "px-3 py-1.5 text-xs"}`}>
        + Add to plan
      </button>
    </form>
  );
}

/** "Mark done" for a recommendation, with the three things a measurement
 * needs: what changed, where, and when. Opens in place; no script needed. */
export function DoneForm({
  id,
  defaultUrl = "",
  primary = false,
}: {
  id: number;
  defaultUrl?: string;
  primary?: boolean;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const field =
    "w-full rounded-md border border-[var(--border)] bg-[var(--inset)] px-2.5 py-1.5 text-[13px]";
  return (
    <details className="group">
      <summary
        className={`btn inline-flex cursor-pointer list-none whitespace-nowrap px-3 py-1.5 text-xs [&::-webkit-details-marker]:hidden ${
          primary ? "btn-primary" : "btn-ghost"
        }`}
      >
        Mark done
      </summary>
      <form action={markRecommendationDone.bind(null, id)} className="mt-3 grid gap-2 sm:grid-cols-2">
        <label className="text-[12px] text-[var(--text-3)] sm:col-span-2">
          What changed?
          <input
            name="description"
            maxLength={500}
            placeholder="e.g. Added plan prices and a comparison table"
            className={`mt-1 ${field}`}
          />
        </label>
        <label className="text-[12px] text-[var(--text-3)]">
          Where? (the page, if there is one)
          <input name="url" type="url" defaultValue={defaultUrl} placeholder="https://…" className={`mt-1 ${field}`} />
        </label>
        <label className="text-[12px] text-[var(--text-3)]">
          When did it go live?
          <input name="shipped_at" type="date" defaultValue={today} max={today} className={`mt-1 ${field}`} />
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <button className="btn btn-primary whitespace-nowrap px-3 py-1.5 text-xs">Record the fix</button>
          <span className="text-[12px] text-[var(--text-3)]">
            We measure the same answers before and after that date, and report it under Proof it
            worked.
          </span>
        </div>
      </form>
    </details>
  );
}
