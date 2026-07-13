"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";

export async function setRecommendationStatus(recId: number, status: string): Promise<void> {
  const res = await apiFetch(`/api/tenant/recommendations/${recId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(res.error ?? "Update failed");
  revalidatePath("/dashboard/recommendations");
}
