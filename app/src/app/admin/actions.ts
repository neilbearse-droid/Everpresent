"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiFetch } from "@/lib/api";

export type ActionState = { ok: boolean; message: string } | null;

export async function createTenant(_prev: ActionState, formData: FormData): Promise<ActionState> {
  const name = String(formData.get("name") ?? "").trim();
  const slug = String(formData.get("slug") ?? "").trim();
  const res = await apiFetch("/api/admin/tenants", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, slug }),
  });
  if (!res.ok) return { ok: false, message: res.error ?? "Failed to create tenant" };
  revalidatePath("/admin");
  redirect(`/admin/${slug}`);
}

export async function importYaml(
  slug: string,
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const yamlText = String(formData.get("yaml") ?? "");
  const res = await apiFetch<{ imported: Record<string, number>; brand: string }>(
    `/api/admin/tenants/${slug}/import-yaml`,
    { method: "POST", headers: { "Content-Type": "text/plain" }, body: yamlText },
  );
  revalidatePath(`/admin/${slug}`);
  if (!res.ok) return { ok: false, message: res.error ?? "Import failed" };
  const counts = Object.entries(res.data!.imported)
    .map(([k, v]) => `${k}: ${v}`)
    .join(", ");
  return { ok: true, message: `Imported ${res.data!.brand} — ${counts}` };
}

export async function patchTenant(slug: string, patch: Record<string, unknown>): Promise<void> {
  const res = await apiFetch(`/api/admin/tenants/${slug}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(res.error ?? "Update failed");
  revalidatePath(`/admin/${slug}`);
}

export async function linkClerkOrg(slug: string, formData: FormData): Promise<void> {
  await patchTenant(slug, { clerk_org_id: String(formData.get("clerk_org_id") ?? "") });
}

export async function setGovernance(slug: string, approved: boolean): Promise<void> {
  await patchTenant(slug, { ai_processing_approved: approved });
}

export async function triggerRun(slug: string, _prev: ActionState): Promise<ActionState> {
  const res = await apiFetch<{ id: number; status: string; error: string | null }>(
    `/api/admin/tenants/${slug}/runs`,
    { method: "POST" },
  );
  revalidatePath(`/admin/${slug}/runs`);
  if (!res.ok) return { ok: false, message: res.error ?? "Trigger failed" };
  const run = res.data!;
  if (run.status === "gated" || run.status === "failed") {
    return { ok: false, message: `Run #${run.id} recorded as ${run.status}: ${run.error ?? ""}` };
  }
  return { ok: true, message: `Run #${run.id} queued.` };
}

export async function setSpendCap(slug: string, formData: FormData): Promise<void> {
  await patchTenant(slug, {
    monthly_spend_cap_usd: Number(formData.get("monthly_spend_cap_usd") ?? 0),
  });
}

export async function putSchedule(
  slug: string,
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const res = await apiFetch<{ cron_expr: string; enabled: boolean }>(
    `/api/admin/tenants/${slug}/schedule`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cron_expr: String(formData.get("cron_expr") ?? ""),
        enabled: formData.get("enabled") === "on",
      }),
    },
  );
  revalidatePath(`/admin/${slug}`);
  if (!res.ok) return { ok: false, message: res.error ?? "Schedule update failed" };
  return {
    ok: true,
    message: `Schedule saved: ${res.data!.cron_expr} (${res.data!.enabled ? "enabled" : "disabled"})`,
  };
}

export async function setNotifyEmails(slug: string, formData: FormData): Promise<void> {
  const emails = String(formData.get("notify_emails") ?? "")
    .split(",")
    .map((e) => e.trim())
    .filter(Boolean);
  await patchTenant(slug, { notify_emails: emails });
}

export async function toggleSurface(slug: string, code: string, enabled: boolean): Promise<void> {
  const res = await apiFetch(`/api/admin/tenants/${slug}/surfaces`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, enabled }),
  });
  if (!res.ok) throw new Error(res.error ?? "Toggle failed");
  revalidatePath(`/admin/${slug}`);
}
