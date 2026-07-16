import Link from "next/link";
import { apiFetch, type Me, type Tenant } from "@/lib/api";
import { CreateTenantForm } from "./create-tenant-form";

export default async function AdminPage() {
  const me = await apiFetch<Me>("/api/me");
  if (!me.data?.is_superadmin) {
    return (
      <main className="mx-auto max-w-3xl px-8 py-16">
        <h1 className="text-xl font-semibold">Not authorized</h1>
        <p className="mt-2 text-sm text-[var(--text-2)]">
          The admin panel is superadmin-only.
        </p>
      </main>
    );
  }

  const tenants = await apiFetch<Tenant[]>("/api/admin/tenants");

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Admin — Tenants</h1>
        <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
          ← Dashboard
        </Link>
      </header>

      <table className="w-full text-left text-sm">
        <thead className="text-[var(--text-2)]">
          <tr>
            <th className="py-2">Tenant</th>
            <th>Slug</th>
            <th>Status</th>
            <th>Clerk org</th>
            <th>AI processing</th>
          </tr>
        </thead>
        <tbody>
          {(tenants.data ?? []).map((t) => (
            <tr key={t.slug} className="border-t border-[var(--border)]">
              <td className="py-3">
                <Link href={`/admin/${t.slug}`} className="font-medium text-[var(--accent)] hover:underline">
                  {t.name}
                </Link>
              </td>
              <td className="text-[var(--text-2)]">{t.slug}</td>
              <td>{t.status}</td>
              <td className="text-[var(--text-2)]">{t.clerk_org_id ?? "— not linked —"}</td>
              <td>{t.ai_processing_approved ? "approved" : "gated"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <section className="mt-12 max-w-md card p-6">
        <h2 className="mb-4 text-lg font-medium">New tenant</h2>
        <CreateTenantForm />
      </section>
    </main>
  );
}
