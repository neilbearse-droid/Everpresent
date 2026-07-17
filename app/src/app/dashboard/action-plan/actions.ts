"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";

export type ShipState = { ok: boolean; message: string } | null;

export async function markShipped(
  queryText: string,
  _prev: ShipState,
  formData: FormData,
): Promise<ShipState> {
  const res = await apiFetch(`/api/tenant/interventions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query_text: queryText,
      url: String(formData.get("url") ?? "").trim(),
      description: String(formData.get("description") ?? "").trim(),
    }),
  });
  if (!res.ok) return { ok: false, message: res.error ?? "Could not record the fix" };
  revalidatePath("/dashboard/action-plan");
  return { ok: true, message: "Shipped — measurement splits at today's date." };
}

export async function unship(
  interventionId: number,
  _prev: ShipState,
  _formData: FormData,
): Promise<ShipState> {
  const res = await apiFetch(`/api/tenant/interventions/${interventionId}`, {
    method: "DELETE",
  });
  if (!res.ok) return { ok: false, message: res.error ?? "Could not remove" };
  revalidatePath("/dashboard/action-plan");
  return { ok: true, message: "Removed." };
}
