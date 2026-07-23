import Link from "next/link";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { Suspense, type ReactNode } from "react";
import { DateRange } from "./date-range";
import { ThemeToggle } from "./theme-toggle";

/* Minimal 16px stroke icons (currentColor) — no external dependency. */
const I = {
  overview: "M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  brand: "M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z",
  scorecard: "M12 20a8 8 0 1 0-8-8M12 12l4-3",
  personas: "M16 20v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M21 20v-1a4 4 0 0 0-3-3.8M16 5a3 3 0 0 1 0 6",
  queries: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14M20 20l-4-4",
  engines: "M4 6h16M4 12h16M4 18h16",
  citations: "M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1",
  action: "M9 11l3 3 8-8M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9",
  recs: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.2 1 2.5h6c0-1.3.3-1.8 1-2.5A6 6 0 0 0 12 3Z",
  outcome: "M3 17l6-6 4 4 8-8M21 7v5M21 7h-5",
  whitespace: "M4 4h16v16H4zM4 9h16M9 9v11",
  runs: "M22 12h-4l-3 9L9 3l-3 9H2",
} as const;

function Icon({ d }: { d: string }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={d} />
    </svg>
  );
}

const TABS: { href: string; label: string; icon: keyof typeof I }[] = [
  { href: "/dashboard", label: "Overview", icon: "overview" },
  { href: "/dashboard/brand", label: "Brand", icon: "brand" },
  { href: "/dashboard/scorecard", label: "Scorecard", icon: "scorecard" },
  { href: "/dashboard/personas", label: "Personas", icon: "personas" },
  { href: "/dashboard/queries", label: "Queries", icon: "queries" },
  { href: "/dashboard/engines", label: "Engines", icon: "engines" },
  { href: "/dashboard/citations", label: "Citations", icon: "citations" },
  { href: "/dashboard/whitespace", label: "Whitespace", icon: "whitespace" },
  { href: "/dashboard/action-plan", label: "Action Plan", icon: "action" },
  { href: "/dashboard/recommendations", label: "Recommendations", icon: "recs" },
  { href: "/dashboard/outcome", label: "Outcome", icon: "outcome" },
  { href: "/dashboard/runs", label: "Runs", icon: "runs" },
];

function BrandMark() {
  return (
    <span
      className="grid h-7 w-7 place-items-center rounded-lg text-[var(--accent-ink)] shadow-[0_2px_8px_var(--accent-soft)]"
      style={{ background: "linear-gradient(135deg, var(--accent), var(--accent-2))" }}
      aria-hidden
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 3v18M5 8l7-5 7 5M5 16l7 5 7-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export function DashNav({
  active,
  isSuperadmin,
  withDateRange,
}: {
  active: string;
  isSuperadmin?: boolean;
  /** Show the GA4-style date-range picker. Only pages whose data is
   * time-scoped pass this — to-do screens (Action Plan, Recommendations)
   * always reflect the current state. */
  withDateRange?: boolean;
}): ReactNode {
  return (
    <header className="sticky top-0 z-30 -mx-8 mb-8 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--plane)_82%,transparent)] px-8 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <BrandMark />
          <span className="text-[15px] font-semibold tracking-tight text-[var(--text)]">
            EverPresent
          </span>
        </Link>
        <div className="flex items-center gap-3">
          {isSuperadmin && (
            <Link
              href="/admin"
              className="rounded-md px-2.5 py-1.5 text-sm text-[var(--text-2)] transition-colors hover:bg-[color-mix(in_srgb,var(--text)_7%,transparent)] hover:text-[var(--text)]"
            >
              Admin
            </Link>
          )}
          <ThemeToggle />
          <OrganizationSwitcher hidePersonal />
          <UserButton />
        </div>
      </div>
      <nav className="mx-auto -mb-px flex max-w-6xl items-center gap-0.5 overflow-x-auto pb-0">
        {TABS.map((tab) => {
          const on = active === tab.label;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={on ? "page" : undefined}
              className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-[13px] font-medium transition-colors ${
                on
                  ? "border-[var(--accent)] text-[var(--text)]"
                  : "border-transparent text-[var(--text-3)] hover:text-[var(--text-2)]"
              }`}
            >
              <span className={on ? "text-[var(--accent)]" : ""}>
                <Icon d={I[tab.icon]} />
              </span>
              {tab.label}
            </Link>
          );
        })}
        {withDateRange && (
          <div className="ml-auto shrink-0 py-1 pl-4">
            <Suspense>
              <DateRange />
            </Suspense>
          </div>
        )}
      </nav>
    </header>
  );
}
