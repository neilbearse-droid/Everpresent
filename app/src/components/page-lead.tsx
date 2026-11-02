import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Every dashboard screen opens with the same two answers, computed from the
 * page's own data: what this screen is telling you, and what to do about it.
 * One or two plain sentences each, with the numbers that matter in them.
 * Charts and tables below are the evidence; this is the conclusion.
 *
 * `tone` colours the "tells" verdict: good news, bad news, or neither.
 */
export function PageLead({
  tells,
  act,
  href,
  hrefLabel,
  tone = "neutral",
}: {
  tells: ReactNode;
  act: ReactNode;
  /** Where the action happens, if it is somewhere else in the product. */
  href?: string;
  hrefLabel?: string;
  tone?: "good" | "bad" | "neutral";
}) {
  return (
    <section className="blueprint mb-6 grid-cols-1 md:grid-cols-2" aria-label="Summary">
      <div className="p-5">
        <div className="mb-2 flex items-center gap-2">
          <span className="bp-label">What this tells you</span>
          {tone !== "neutral" && (
            <span className={`pill ${tone === "good" ? "pill-good" : "pill-bad"}`}>
              {tone === "good" ? "Good" : "Needs attention"}
            </span>
          )}
        </div>
        <p className="text-[15px] leading-relaxed text-[var(--text)]">{tells}</p>
      </div>
      <div className="p-5">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="bp-label">What to do</span>
          {href && (
            <Link href={href} className="text-[12.5px] font-medium text-[var(--accent)] hover:underline">
              {hrefLabel ?? "Go"} →
            </Link>
          )}
        </div>
        <p className="text-[15px] leading-relaxed text-[var(--text)]">{act}</p>
      </div>
    </section>
  );
}
