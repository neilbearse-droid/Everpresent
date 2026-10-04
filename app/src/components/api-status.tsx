import { apiFetch } from "@/lib/api";

/** A page whose API calls failed must say so, not show an empty state that
 * reads like "no data yet". One cheap health call per page. */
export async function ApiDownBanner() {
  const res = await apiFetch<{ status: string }>("/api/health");
  if (res.ok) return null;
  return (
    <div
      role="alert"
      className="mx-auto mt-4 max-w-[1400px] px-6"
    >
      <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm">
        <span className="bp-neg mr-2">Offline</span>
        Can&apos;t reach the EverPresent API right now, so the numbers on this page may be missing.
        Refresh in a minute.
      </p>
    </div>
  );
}
