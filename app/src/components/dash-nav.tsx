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

export function Wordmark({ inverted = false }: { inverted?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="block h-4 w-4 bg-[var(--accent)] outline-2 outline-offset-0 outline-[var(--line)]" aria-hidden />
      <span
        className={`font-mono text-[15px] font-extrabold uppercase tracking-[0.04em] ${
          inverted ? "text-[var(--bar-text)]" : "text-[var(--text)]"
        }`}
      >
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
    <header className="bp-bleed sticky top-0 z-30 mb-6">
      <div className="flex h-12 items-center justify-between bg-[var(--bar)] px-6">
        <Link href="/dashboard">
          <Wordmark inverted />
        </Link>
        <div className="flex items-center gap-4 font-mono text-[12px] uppercase text-[var(--bar-text)]">
          {isSuperadmin && (
            <Link href="/admin" className="hover:text-[var(--accent)]">
              [Admin]
            </Link>
          )}
          <ThemeToggle />
          <OrganizationSwitcher
            hidePersonal
            // The trigger inherits Clerk's dark text: invisible on the black bar.
            appearance={{
              elements: {
                organizationSwitcherTrigger:
                  "text-[var(--bar-text)] hover:text-[var(--accent)] focus:shadow-none",
                organizationPreviewMainIdentifier: "text-[var(--bar-text)]",
                organizationSwitcherTriggerIcon: "text-[var(--bar-text)]",
              },
            }}
          />
          <UserButton />
        </div>
      </div>
      <nav className="flex items-stretch overflow-x-auto border-b-2 border-[var(--line)] bg-[var(--surface)]">
        {TABS.map((tab) => {
          const on = active === tab.label;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={on ? "page" : undefined}
              className={`shrink-0 border-r-2 border-[var(--line)] px-3.5 py-2.5 font-mono text-[11.5px] font-bold uppercase tracking-[0.03em] ${
                on
                  ? "bg-[var(--accent)] text-[var(--accent-ink)]"
                  : "text-[var(--text)] hover:bg-[var(--line)] hover:text-[var(--surface)]"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
        {withDateRange && (
          <div className="ml-auto flex shrink-0 items-center border-l-2 border-[var(--line)] px-3">
            <Suspense>
              <DateRange />
            </Suspense>
          </div>
        )}
      </nav>
    </header>
  );
}
