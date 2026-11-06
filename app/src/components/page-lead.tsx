import Link from "next/link";
import type { ReactNode } from "react";
import { Emph } from "./ui";

/**
 * Every dashboard screen opens with two short lines computed from its own
 * data: what this screen is telling you, and what to do about it.
 *
 * Budget: `tells` is one sentence of at most about fourteen words, with the
 * number that matters in it. `act` is one imperative sentence of at most
 * about twelve words. Anything longer belongs in the page, not here.
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
    <div className="mb-6 space-y-2" aria-label="Summary">
      <section className="card px-5 py-4">
        <p className="text-[19px] font-semibold leading-snug tracking-[-0.015em] text-[var(--text)]">
          {tone !== "neutral" && (
            <span
              aria-hidden
              className={`mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle ${
                tone === "good" ? "bg-[var(--pos)]" : "bg-[var(--neg)]"
              }`}
            />
          )}
          {typeof tells === "string" ? <Emph text={tells} /> : tells}
        </p>
      </section>
      <section className="card flex flex-wrap items-center gap-x-4 gap-y-2 border-l-[3px] border-l-[var(--accent)] px-5 py-3">
        <span className="bp-label shrink-0">Priority action</span>
        <p className="min-w-0 flex-1 text-[14px] leading-snug text-[var(--text)]">
          {typeof act === "string" ? <Emph text={act} /> : act}
        </p>
        {href && (
          <Link href={href} className="btn btn-primary shrink-0 px-3 text-[12.5px]">
            {hrefLabel ?? "Go"} →
          </Link>
        )}
      </section>
    </div>
  );
}
