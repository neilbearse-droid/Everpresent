import Link from "next/link";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { Suspense, type ReactNode } from "react";
import { DateRange } from "./date-range";
import { ThemeToggle } from "./theme-toggle";

type Tab = { href: string; label: string };

// Grouped by the job the user is doing, top to bottom: see where you stand,
// dig into why, act on it, check the plumbing.
const GROUPS: { title: string; tabs: Tab[]; collapsed?: boolean }[] = [
  {
    title: "Overview",
    tabs: [
      { href: "/dashboard", label: "Overview" },
      { href: "/dashboard/scorecard", label: "Scorecard" },
      { href: "/dashboard/answers", label: "Answer Shape" },
    ],
  },
  {
    title: "Visibility",
    tabs: [
      { href: "/dashboard/engines", label: "Engines" },
      { href: "/dashboard/queries", label: "Queries" },
      { href: "/dashboard/citations", label: "Citations" },
      { href: "/dashboard/pages", label: "Your Pages" },
      { href: "/dashboard/agents", label: "AI Agents" },
    ],
  },
  {
    title: "Act",
    tabs: [
      { href: "/dashboard/recommendations", label: "Recommendations" },
      { href: "/dashboard/outcome", label: "Outcome" },
    ],
  },
  {
    title: "More",
    collapsed: true,
    tabs: [
      { href: "/dashboard/brand", label: "Brand" },
      { href: "/dashboard/personas", label: "Personas" },
      { href: "/dashboard/fanout", label: "Fan-out" },
      { href: "/dashboard/whitespace", label: "Whitespace" },
      { href: "/dashboard/action-plan", label: "Action Plan" },
      { href: "/dashboard/runs", label: "Runs" },
    ],
  },
];
const TABS: Tab[] = GROUPS.flatMap((g) => g.tabs);

export function Wordmark({ inverted = false }: { inverted?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span className="relative block h-5 w-5 rounded-[5px] bg-[var(--accent)]" aria-hidden>
        <span className="absolute inset-[5px] rounded-full border-2 border-white" />
      </span>
      <span
        className={`text-[15px] font-semibold tracking-[-0.025em] ${
          inverted ? "text-white" : "text-[var(--text)]"
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
            <Wordmark inverted />
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
                  "w-full justify-between rounded-md border border-[var(--side-line)] bg-white/5! px-2.5 py-1.5 text-white! shadow-none hover:bg-white/10! focus:shadow-none",
                // Colors live in globals.css: white on the navy trigger, dark
                // ink in the white popover.
                organizationPreviewMainIdentifier: "text-[13px] font-semibold",
                organizationSwitcherTriggerIcon: "text-[var(--side-muted)]!",
              },
            }}
          />
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          {GROUPS.map((g) => {
            const links = (
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
            );
            return g.collapsed ? (
              <details key={g.title} className="mt-4" open={group === g.title}>
                <summary className="eyebrow mb-1.5 cursor-pointer list-none px-2.5">
                  {g.title} ▾
                </summary>
                {links}
              </details>
            ) : (
              <div key={g.title} className="mt-4 first:mt-1">
                <p className="eyebrow mb-1.5 px-2.5">{g.title}</p>
                {links}
              </div>
            );
          })}
        </nav>
        <div className="ep-side-foot flex items-center justify-between px-4 py-3">
          <UserButton />
          <div className="flex items-center gap-1">
            {isSuperadmin && (
              <Link
                href="/admin"
                className="ep-side-btn rounded-md px-2 py-1 text-[12.5px] font-medium"
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
      <div className="mb-6 flex min-h-12 flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] pb-3 pt-2 lg:pt-5">
        <p className="text-[13px] font-medium text-[var(--text-3)]">
          {group && group !== active ? (
            <>
              {group} <span className="px-1.5 text-[var(--border-strong)]">/</span>
              <span className="font-semibold text-[var(--text)]">{active}</span>
            </>
          ) : (
            <span className="font-semibold text-[var(--text)]">{active}</span>
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
