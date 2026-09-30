import Link from "next/link";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { Suspense, type ReactNode } from "react";
import { DateRange } from "./date-range";
import { ThemeToggle } from "./theme-toggle";

const TABS: { href: string; label: string }[] = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/brand", label: "Brand" },
  { href: "/dashboard/scorecard", label: "Scorecard" },
  { href: "/dashboard/personas", label: "Personas" },
  { href: "/dashboard/queries", label: "Queries" },
  { href: "/dashboard/engines", label: "Engines" },
  { href: "/dashboard/fanout", label: "Fan-out" },
  { href: "/dashboard/citations", label: "Citations" },
  { href: "/dashboard/whitespace", label: "Whitespace" },
  { href: "/dashboard/action-plan", label: "Action Plan" },
  { href: "/dashboard/recommendations", label: "Recommendations" },
  { href: "/dashboard/outcome", label: "Outcome" },
  { href: "/dashboard/runs", label: "Runs" },
];

export function Wordmark() {
  return (
    <span className="flex items-center gap-2">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
        <rect x="0" y="0" width="18" height="18" rx="3" fill="var(--ink)" />
        <circle cx="9" cy="9" r="3.25" fill="var(--ink-text)" />
      </svg>
      <span className="text-[15px] font-semibold tracking-[-0.015em] text-[var(--text)]">
        EverPresent
      </span>
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
    <header className="sticky top-0 z-30 -mx-8 mb-10 border-b border-[var(--border)] bg-[var(--plane)] px-8">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between">
        <Link href="/dashboard">
          <Wordmark />
        </Link>
        <div className="flex items-center gap-4">
          {isSuperadmin && (
            <Link
              href="/admin"
              className="text-[13px] text-[var(--text-2)] hover:text-[var(--text)]"
            >
              Admin
            </Link>
          )}
          <ThemeToggle />
          <OrganizationSwitcher hidePersonal />
          <UserButton />
        </div>
      </div>
      <nav className="mx-auto -mb-px flex max-w-6xl items-end gap-6 overflow-x-auto">
        {TABS.map((tab) => {
          const on = active === tab.label;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={on ? "page" : undefined}
              className={`shrink-0 border-b-2 pb-2.5 pt-1 text-[13px] transition-colors ${
                on
                  ? "border-[var(--ink)] font-medium text-[var(--text)]"
                  : "border-transparent text-[var(--text-2)] hover:text-[var(--text)]"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
        {withDateRange && (
          <div className="ml-auto shrink-0 pb-2 pl-4">
            <Suspense>
              <DateRange />
            </Suspense>
          </div>
        )}
      </nav>
    </header>
  );
}
