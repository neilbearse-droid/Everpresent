import { addToPlan, setRecommendationStatus } from "@/app/dashboard/recommendations/actions";

/** Start / Mark done / Dismiss for a recommendation that already exists. */
export function StatusButtons({ id, status, compact = false }: { id: number; status: string; compact?: boolean }) {
  const btn = `btn whitespace-nowrap ${compact ? "px-2.5 py-1 text-[12px]" : "px-3 py-1.5 text-xs"}`;
  const next: { to: string; label: string; primary?: boolean }[] =
    status === "open"
      ? [{ to: "in_progress", label: "Start", primary: true }, { to: "dismissed", label: "Dismiss" }]
      : status === "in_progress"
        ? [{ to: "done", label: "Mark done", primary: true }, { to: "open", label: "Stop" }]
        : [{ to: "open", label: "Reopen" }];
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
