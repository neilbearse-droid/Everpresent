import type { AIOSummary } from "@/lib/api";

/** How often Google's AI Overview answers the corpus, and whether the brand is
 * among its sources. `bare` renders it as a blueprint cell (no card frame). */
export function AIOTile({ aio, bare = true }: { aio: AIOSummary; bare?: boolean }) {
  const frame = bare ? "p-3" : "card p-4";
  if (aio.queries_measured === 0) {
    return (
      <div className={frame}>
        <div className="bp-label mb-1">Google AI Overviews</div>
        <div className="bp-head text-[14px] text-[var(--text-3)]">Not measured</div>
      </div>
    );
  }
  return (
    <div className={frame}>
      <div className="bp-label mb-1">Google AI Overviews</div>
      <div className="flex items-baseline gap-2">
        <span className="bp-metric text-[34px]">{aio.aio_share_pct}%</span>
        <span className="text-[11.5px] leading-tight text-[var(--text-2)]">
          of {aio.queries_measured} queries trigger an AI Overview
        </span>
      </div>
      <div className="mt-1 text-[12px]">
        {aio.brand_cited_in_aio > 0 ? (
          <span>Brand cited as a source in {aio.brand_cited_in_aio}</span>
        ) : (
          <span className="bp-alert">Brand is never an AIO source</span>
        )}
      </div>
    </div>
  );
}
