"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

/** GA4-style date-range control. The selected range lives in the URL
 * (?from=YYYY-MM-DD&to=YYYY-MM-DD) so it survives reloads and is shareable;
 * server pages forward it to the API as start/end. No params = all time. */

const PRESETS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 28 days", days: 28 },
  { label: "Last 90 days", days: 90 },
] as const;

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function presetRange(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - (days - 1) * 86400000);
  return { from: iso(from), to: iso(to) };
}

function fmt(date: string): string {
  const d = new Date(`${date}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function DateRange() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [open, setOpen] = useState(false);

  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const [draftFrom, setDraftFrom] = useState(from);
  const [draftTo, setDraftTo] = useState(to);

  function apply(nextFrom: string, nextTo: string) {
    const next = new URLSearchParams(params.toString());
    if (nextFrom) next.set("from", nextFrom);
    else next.delete("from");
    if (nextTo) next.set("to", nextTo);
    else next.delete("to");
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
    setOpen(false);
  }

  const label = from || to ? `${from ? fmt(from) : "…"} – ${to ? fmt(to) : "today"}` : "All time";

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => {
          setDraftFrom(from);
          setDraftTo(to);
          setOpen(!open);
        }}
        className="btn btn-ghost gap-2 px-2.5 py-1 text-[11px]"
        aria-expanded={open}
      >
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="square"
          aria-hidden
        >
          <rect x="3" y="5" width="18" height="16" />
          <path d="M8 3v4M16 3v4M3 10h18" />
        </svg>
        {label}
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <>
          <button
            aria-label="Close date picker"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="card absolute right-0 z-50 mt-3 w-64 p-3">
            <div className="mb-2 flex flex-col gap-0.5">
              {PRESETS.map((p) => {
                const r = presetRange(p.days);
                const active = from === r.from && to === r.to;
                return (
                  <button
                    key={p.label}
                    onClick={() => apply(r.from, r.to)}
                    className={`rounded-md px-2.5 py-1.5 text-left text-[13px] ${
                      active
                        ? "bg-[var(--surface-2)] font-medium text-[var(--text)]"
                        : "text-[var(--text-2)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]"
                    }`}
                  >
                    {p.label}
                  </button>
                );
              })}
              <button
                onClick={() => apply("", "")}
                className={`rounded-md px-2.5 py-1.5 text-left text-[13px] ${
                  !from && !to
                    ? "bg-[var(--surface-2)] font-medium text-[var(--text)]"
                    : "text-[var(--text-2)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]"
                }`}
              >
                All time
              </button>
            </div>
            <div className="border-t border-[var(--border)] pt-2">
              <p className="eyebrow mb-1.5">Custom</p>
              <div className="flex items-center gap-1.5">
                <input
                  type="date"
                  value={draftFrom}
                  onChange={(e) => setDraftFrom(e.target.value)}
                  className="field w-full px-1.5 py-1 text-xs"
                  aria-label="From date"
                />
                <span className="text-xs text-[var(--text-3)]">–</span>
                <input
                  type="date"
                  value={draftTo}
                  onChange={(e) => setDraftTo(e.target.value)}
                  className="field w-full px-1.5 py-1 text-xs"
                  aria-label="To date"
                />
              </div>
              <button
                onClick={() => apply(draftFrom, draftTo)}
                className="btn btn-primary mt-2 w-full px-2 py-1.5 text-xs"
              >
                Apply
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
