"use client";

import Link from "next/link";

/** Recoverable error screen for route error boundaries. Production builds
 * redact server error messages, so the copy stays generic and the digest is
 * shown for log lookup. */
export function ErrorPanel({
  error,
  reset,
  homeHref,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  homeHref: string;
}) {
  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <section className="card p-6">
        <p className="bp-label mb-2">Something went wrong</p>
        <h1 className="mb-3 text-xl font-semibold">That didn&apos;t load.</h1>
        <p className="mb-5 text-sm text-[var(--text-2)]">
          The change may not have saved. Try again. If it keeps happening, the API may be
          restarting, so give it a minute.
          {error.digest && (
            <span className="mt-2 block font-mono text-xs">ref: {error.digest}</span>
          )}
        </p>
        <div className="flex gap-3">
          <button type="button" onClick={reset} className="btn btn-primary">
            Try again
          </button>
          <Link href={homeHref} className="btn btn-ghost">
            Back
          </Link>
        </div>
      </section>
    </main>
  );
}
