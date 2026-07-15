import { DashNav } from "@/components/dash-nav";

/** Shown when a dashboard tab loads without an active organization. The
 * tenant-scoped API returns 403 in that case; every tab renders this instead
 * of its own "no data" empty state, so an unselected org never masquerades as
 * an empty tenant. */
export function NoOrgNotice({
  active,
  isSuperadmin,
  detail,
}: {
  active: string;
  isSuperadmin?: boolean;
  detail?: string | null;
}) {
  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      <DashNav active={active} isSuperadmin={isSuperadmin} />
      <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-2 text-lg font-medium">No organization selected</h2>
        <p className="text-sm text-slate-400">
          Pick an organization in the switcher above to see its dashboards, or ask your
          EverPresent contact for an invite.
          {detail ? <span className="ml-1 text-slate-500">({detail})</span> : null}
        </p>
      </section>
    </main>
  );
}
