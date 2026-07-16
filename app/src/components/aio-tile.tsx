import type { AIOSummary } from "@/lib/api";

/** The M6 gate tile: how often Google's AI Overview answers the corpus, and
 * whether the brand is among its sources. */
export function AIOTile({ aio }: { aio: AIOSummary }) {
  if (aio.queries_measured === 0) {
    return (
      <div className="card p-5">
        <div className="text-3xl font-semibold text-[var(--text-3)]">—</div>
        <div className="mt-1 text-sm text-[var(--text-2)]">
          Google AIO share (enable the google_aio surface and run)
        </div>
      </div>
    );
  }
  return (
    <div className="card p-5">
      <div className="text-3xl font-semibold tabular-nums">{aio.aio_share_pct}%</div>
      <div className="mt-1 text-sm text-[var(--text-2)]">
        of {aio.queries_measured} measured queries trigger Google's AI Overview
      </div>
      <div className="mt-2 text-sm">
        {aio.brand_cited_in_aio > 0 ? (
          <span className="text-[var(--pos)]">
            Brand cited as a source in {aio.brand_cited_in_aio}
          </span>
        ) : (
          <span className="text-[var(--warn-t)]">Brand is never an AIO source</span>
        )}
      </div>
    </div>
  );
}
