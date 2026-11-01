"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";

export type ControlState = { ok: boolean; message: string } | null;

async function patchQuery(id: number, body: Record<string, unknown>): Promise<ControlState> {
  const res = await apiFetch<{ id: number; active: boolean }>(`/api/tenant/queries/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return { ok: false, message: res.error ?? "Could not save" };
  revalidatePath("/dashboard/queries");
  return { ok: true, message: "" };
}

export async function setQueryActive(
  id: number,
  active: boolean,
  _prev: ControlState,
  _formData: FormData,
): Promise<ControlState> {
  const out = await patchQuery(id, { active });
  if (out?.ok) {
    return {
      ok: true,
      message: active
        ? "Back in the next run."
        : "Paused. It leaves the next run and the rates from today; its history stays below.",
    };
  }
  return out;
}

export async function setQueryPersonas(
  id: number,
  segments: string[],
  _prev: ControlState,
  formData: FormData,
): Promise<ControlState> {
  const chosen = segments.filter((s) => formData.get(`p_${s}`) === "on");
  const out = await patchQuery(id, { persona_segments: chosen });
  if (out?.ok) return { ok: true, message: "Saved. Applies from the next run." };
  return out;
}
