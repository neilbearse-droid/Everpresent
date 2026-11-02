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
    <section className="card mb-6 px-5 py-4" aria-label="Summary">
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3">
        <div className="min-w-0 flex-1 basis-[28rem]">
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
        </div>
        <div className="flex min-w-0 flex-1 basis-[20rem] items-start gap-3 lg:justify-end">
          <p className="text-[14px] leading-snug text-[var(--text-2)]">
            <span className="font-semibold text-[var(--text)]">Do: </span>
            {act}
          </p>
          {href && (
            <Link href={href} className="btn btn-ghost shrink-0 px-3 text-[12.5px]">
              {hrefLabel ?? "Go"} →
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
