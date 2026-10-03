import Link from "next/link";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { Suspense, type ReactNode } from "react";
import { DateRange } from "./date-range";
import { ThemeToggle } from "./theme-toggle";

type Tab = { href: string; label: string };

// Grouped by the job the user is doing, top to bottom: see where you stand,
// dig into why, act on it, check the plumbing.
const GROUPS: { title: string; tabs: Tab[] }[] = [
  {
    title: "Overview",
    tabs: [
      { href: "/dashboard", label: "Overview" },
      { href: "/dashboard/scorecard", label: "Scorecard" },
      { href: "/dashboard/engines", label: "Engines" },
      { href: "/dashboard/personas", label: "Personas" },
    ],
  },
  {
    title: "Visibility",
    tabs: [
      { href: "/dashboard/brand", label: "Brand" },
      { href: "/dashboard/queries", label: "Queries" },
      { href: "/dashboard/fanout", label: "Fan-out" },
      { href: "/dashboard/citations", label: "Citations" },
      { href: "/dashboard/whitespace", label: "Whitespace" },
      { href: "/dashboard/agents", label: "AI Agents" },
    ],
  },
  {
    title: "Act",
    tabs: [
      { href: "/dashboard/recommendations", label: "Recommendations" },
      { href: "/dashboard/action-plan", label: "Action Plan" },
      { href: "/dashboard/outcome", label: "Outcome" },
    ],
  },
  {
    title: "System",
    tabs: [{ href: "/dashboard/runs", label: "Runs" }],
  },
];
const TABS: Tab[] = GROUPS.flatMap((g) => g.tabs);

export function Wordmark({ inverted = false }: { inverted?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span className="relative block h-[18px] w-[18px]" aria-hidden>
        <span className="absolute inset-0 rounded-full bg-[var(--accent)]" />
        <span className="absolute inset-[5px] rounded-full bg-[var(--plane)]" />
      </span>
      <span
        className={`text-[15px] font-semibold tracking-[-0.03em] ${
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
  const group = GROUPS.find((g) => g.tabs.some((t) => t.label === active))?.title;
  return (
    <>
      {/* Desktop: a fixed sidebar (the body reserves its width in CSS). */}
      <aside className="ep-side fixed inset-y-0 left-0 z-30 hidden w-[248px] flex-col lg:flex">
        <div className="flex h-14 items-center px-5">
          <Link href="/dashboard">
            <Wordmark />
          </Link>
        </div>
        <div className="px-3 pb-3">
          <OrganizationSwitcher
            hidePersonal
            appearance={{
              elements: {
                rootBox: "w-full",
                // `!` (important): Clerk's own unlayered styles would otherwise
                // win over Tailwind's layered utilities and keep dark text in
                // dark mode.
                organizationSwitcherTrigger:
                  "w-full justify-between rounded-lg border border-[var(--border)] bg-[var(--surface)]! px-2.5 py-1.5 text-[var(--text)]! shadow-none focus:shadow-none",
                organizationPreviewMainIdentifier: "text-[13px] font-medium text-[var(--text)]!",
                organizationSwitcherTriggerIcon: "text-[var(--text-3)]!",
              },
            }}
          />
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          {GROUPS.map((g) => (
            <div key={g.title} className="mt-4 first:mt-1">
              <p className="eyebrow mb-1.5 px-2.5">{g.title}</p>
              <ul className="space-y-0.5">
                {g.tabs.map((tab) => (
                  <li key={tab.href}>
                    <Link
                      href={tab.href}
                      aria-current={active === tab.label ? "page" : undefined}
                      className="ep-navlink"
                    >
                      <span className="ep-dot" aria-hidden />
                      {tab.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="flex items-center justify-between border-t border-[var(--line)] px-4 py-3">
          <UserButton />
          <div className="flex items-center gap-1">
            {isSuperadmin && (
              <Link
                href="/admin"
                className="rounded-md px-2 py-1 text-[12.5px] text-[var(--text-2)] hover:bg-[var(--plane-2)] hover:text-[var(--text)]"
              >
                Admin
              </Link>
            )}
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* Mobile: a compact top bar with scrolling tabs. */}
      <header className="sticky top-0 z-30 -mx-6 mb-6 border-b border-[var(--line)] bg-[var(--scrim)] backdrop-blur-md lg:hidden">
        <div className="flex h-12 items-center justify-between px-4">
          <Link href="/dashboard">
            <Wordmark />
          </Link>
          <div className="flex items-center gap-2">
            {isSuperadmin && (
              <Link href="/admin" className="text-[12.5px] text-[var(--text-2)]">
                Admin
              </Link>
            )}
            <ThemeToggle />
            <UserButton />
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-2">
          {TABS.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active === tab.label ? "page" : undefined}
              className="ep-navlink shrink-0 py-1 text-[13px]"
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </header>

      {/* Page toolbar: where you are, and the date range when it applies. */}
      <div className="mb-6 flex min-h-12 flex-wrap items-center justify-between gap-3 pt-2 lg:pt-5">
        <p className="text-[13px] text-[var(--text-3)]">
          {group && group !== active ? (
            <>
              {group} <span className="px-1 text-[var(--text-3)]">/</span>
              <span className="text-[var(--text-2)]">{active}</span>
            </>
          ) : (
            <span className="text-[var(--text-2)]">{active}</span>
          )}
        </p>
        {withDateRange && (
          <Suspense>
            <DateRange />
          </Suspense>
        )}
      </div>
    </>
  );
}
