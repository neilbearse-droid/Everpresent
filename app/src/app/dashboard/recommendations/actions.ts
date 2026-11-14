"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";

function refresh() {
  revalidatePath("/dashboard");
  revalidatePath("/dashboard/recommendations");
  revalidatePath("/dashboard/outcome");
}

/** "Mark done" with what changed, where and when. The fix is logged as an
 * experiment: the same answers are measured before and after the date. */
export async function markRecommendationDone(recId: number, formData: FormData): Promise<void> {
  const res = await apiFetch(`/api/tenant/recommendations/${recId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      status: "done",
      fix: {
        description: String(formData.get("description") ?? "").trim(),
        url: String(formData.get("url") ?? "").trim(),
        shipped_at: String(formData.get("shipped_at") ?? "").trim() || null,
      },
    }),
  });
  if (!res.ok) throw new Error(res.error ?? "Could not record the fix");
  refresh();
}

export async function setRecommendationStatus(recId: number, status: string): Promise<void> {
  const res = await apiFetch(`/api/tenant/recommendations/${recId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(res.error ?? "Update failed");
  refresh();
}

/** "Add to plan" from anywhere an action is shown. `gapRef` is the caller's
 * stable id for the action, so pressing it twice updates one item. */
export async function addToPlan(input: {
  gapRef: string;
  title: string;
  actionText?: string;
  link?: string;
  queryText?: string;
}): Promise<void> {
  const res = await apiFetch("/api/tenant/recommendations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      gap_ref: input.gapRef,
      title: input.title,
      action_text: input.actionText ?? "",
      link: input.link ?? "",
      query_text: input.queryText ?? "",
    }),
  });
  if (!res.ok) throw new Error(res.error ?? "Could not add to plan");
  refresh();
}
