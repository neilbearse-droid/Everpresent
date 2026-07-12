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

export async function toggleSurface(slug: string, code: string, enabled: boolean): Promise<void> {
  const res = await apiFetch(`/api/admin/tenants/${slug}/surfaces`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, enabled }),
  });
  if (!res.ok) throw new Error(res.error ?? "Toggle failed");
  revalidatePath(`/admin/${slug}`);
}
