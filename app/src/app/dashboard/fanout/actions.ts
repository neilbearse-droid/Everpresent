"use server";

import { apiFetch, type ContentDraft } from "@/lib/api";

export type BriefState =
  | { ok: true; draft: ContentDraft }
  | { ok: false; message: string }
  | null;

export async function generateBrief(
  shardId: number,
  _prev: BriefState,
  _formData: FormData,
): Promise<BriefState> {
  const res = await apiFetch<ContentDraft>(`/api/tenant/content/fanout/${shardId}/draft`, {
    method: "POST",
  });
  if (!res.ok || !res.data) {
    return { ok: false, message: res.error ?? "Could not generate the brief" };
  }
  return { ok: true, draft: res.data };
}
