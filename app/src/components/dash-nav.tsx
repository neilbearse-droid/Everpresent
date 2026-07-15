import Link from "next/link";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";

const TABS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/personas", label: "Personas" },
  { href: "/dashboard/queries", label: "Queries" },
  { href: "/dashboard/citations", label: "Citations" },
  { href: "/dashboard/recommendations", label: "Recommendations" },
  { href: "/dashboard/runs", label: "Runs" },
];

export function DashNav({ active, isSuperadmin }: { active: string; isSuperadmin?: boolean }) {
  return (
    <header className="mb-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">EverPresent</h1>
        <div className="flex items-center gap-4">
          {isSuperadmin && (
            <Link href="/admin" className="text-sm text-indigo-400 hover:underline">
              Admin
            </Link>
          )}
          <OrganizationSwitcher hidePersonal />
          <UserButton />
        </div>
      </div>
      <nav className="mt-6 flex gap-1 border-b border-slate-800">
        {TABS.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className={`rounded-t-md px-4 py-2 text-sm ${
              active === tab.label
                ? "border-b-2 border-indigo-400 font-medium text-slate-100"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
