import Link from "next/link";
import { apiFetch, type Me, type WaitlistReport } from "@/lib/api";
import { SignupRow } from "./signup-row";

export const metadata = { title: "Waitlist" };

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  contacted: "Contacted",
  invited: "Invited",
  activated: "Activated",
  declined: "Declined",
};

export default async function WaitlistPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const me = await apiFetch<Me>("/api/me");
  if (!me.data?.is_superadmin) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16 sm:px-8">
        <h1 className="text-xl font-semibold">Not authorized</h1>
        <p className="mt-2 text-sm text-[var(--text-2)]">
          Only EverPresent admins can open this page.
        </p>
      </main>
    );
  }

  const { status = "" } = await searchParams;
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const report = await apiFetch<WaitlistReport>(`/api/admin/waitlist${query}`);
  const data = report.data;

  return (
    <main className="mx-auto max-w-[1200px] px-4 py-10 sm:px-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Waitlist</h1>
          <p className="mt-1 text-sm text-[var(--text-2)]">
            Signups from the everpresent.io landing page. Move a row along as you work it.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <a href="/admin/waitlist/export" className="bp-link text-sm">
            Download CSV
          </a>
          <Link href="/admin" className="text-sm text-[var(--accent)] hover:underline">
            ← Clients
          </Link>
        </div>
      </header>

      {!data && (
        <p className="card p-6 text-sm text-[var(--text-2)]">
          {report.error ?? "Could not load the waitlist."}
        </p>
      )}

      {data && (
        <>
          <div className="mb-6 flex flex-wrap items-center gap-2">
            <Link
              href="/admin/waitlist"
              className={`chip ${status ? "" : "pill-good"}`}
            >
              All {data.counts.total ?? 0}
            </Link>
            {data.statuses.map((option) => (
              <Link
                key={option}
                href={`/admin/waitlist?status=${option}`}
                className={`chip ${status === option ? "pill-good" : ""}`}
              >
                {STATUS_LABEL[option] ?? option} {data.counts[option] ?? 0}
              </Link>
            ))}
          </div>

          {data.signups.length === 0 ? (
            <p className="card p-6 text-sm text-[var(--text-2)]">
              No signups here yet.
            </p>
          ) : (
            <div className="blueprint">
              <table className="bp-table w-full">
                <thead>
                  <tr>
                    <th>Joined</th>
                    <th>Person</th>
                    <th>Company</th>
                    <th>Industry</th>
                    <th>Source</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.signups.map((signup) => (
                    <SignupRow key={signup.id} signup={signup} statuses={data.statuses} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </main>
  );
}
