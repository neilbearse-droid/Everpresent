import { UserButton } from "@clerk/nextjs";
import { currentUser } from "@clerk/nextjs/server";

export default async function DashboardPage() {
  const user = await currentUser();
  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-10 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">EverPresent</h1>
        <UserButton />
      </header>
      <section className="rounded-lg border border-slate-700 bg-slate-900 p-6">
        <h2 className="mb-2 text-lg font-medium">
          Welcome{user?.firstName ? `, ${user.firstName}` : ""}
        </h2>
        <p className="text-sm text-slate-400">
          M0 checkpoint: you are logged in. Tenant dashboards arrive with M1–M3 — next up:
          tenancy, the admin panel, and YAML import of the launch tenants.
        </p>
      </section>
    </main>
  );
}
