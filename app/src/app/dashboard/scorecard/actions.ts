"use server";

import { apiFetch, type ContentDraft } from "@/lib/api";

export type DraftState =
  | { ok: true; draft: ContentDraft }
  | { ok: false; message: string }
  | null;

export async function generateDraft(
  factId: number,
  _prev: DraftState,
  _formData: FormData,
): Promise<DraftState> {
  const res = await apiFetch<ContentDraft>(
    `/api/tenant/content/accuracy/${factId}/draft`,
    { method: "POST" },
  );
  if (!res.ok || !res.data) {
    return { ok: false, message: res.error ?? "Could not generate content" };
  }
  return { ok: true, draft: res.data };
}
