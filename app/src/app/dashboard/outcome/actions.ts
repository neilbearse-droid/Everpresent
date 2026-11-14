"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";

/** Remove a fix from the proof list (logged by mistake, or a detected change
 * that wasn't a real edit). The page changes the crawl saw are kept. */
export async function removeFix(interventionId: number): Promise<void> {
  const res = await apiFetch(`/api/tenant/interventions/${interventionId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(res.error ?? "Could not remove the fix");
  revalidatePath("/dashboard/outcome");
  revalidatePath("/dashboard/action-plan");
}
