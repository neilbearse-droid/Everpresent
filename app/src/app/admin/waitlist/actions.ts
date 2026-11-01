"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";
import type { ActionState } from "../actions";

export async function updateSignup(
  signupId: number,
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const status = String(formData.get("status") ?? "");
  const note = String(formData.get("note") ?? "");
  const res = await apiFetch(`/api/admin/waitlist/${signupId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, note }),
  });
  if (!res.ok) return { ok: false, message: res.error ?? "Could not save" };
  revalidatePath("/admin/waitlist");
  return { ok: true, message: "Saved." };
}
