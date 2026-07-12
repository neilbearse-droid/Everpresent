import { auth } from "@clerk/nextjs/server";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

export type ApiResult<T> = {
  ok: boolean;
  status: number;
  data: T | null;
  error: string | null;
};

/** Server-side fetch to the FastAPI backend, forwarding the Clerk session
 * token. The API resolves the tenant from the token's org claim — the
 * frontend never passes a tenant identifier for client-facing reads. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  const { getToken } = await auth();
  const token = await getToken();
  const res = await fetch(`${API_ORIGIN}${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    cache: "no-store",
  });
  let data: T | null = null;
  let error: string | null = null;
  const body = await res.text();
  try {
    const parsed = body ? JSON.parse(body) : null;
    if (res.ok) {
      data = parsed as T;
    } else {
      error =
        typeof parsed?.detail === "string" ? parsed.detail : (body ?? `HTTP ${res.status}`);
    }
  } catch {
    error = res.ok ? null : body || `HTTP ${res.status}`;
  }
  return { ok: res.ok, status: res.status, data, error };
}

export type Me = {
  email: string;
  display_name: string | null;
  is_superadmin: boolean;
  org_id: string | null;
};

export type TenantSummary = {
  name: string;
  slug: string;
  status: string;
  role: string;
  brand_name: string | null;
  ai_processing_approved: boolean;
  counts: { competitors: number; personas: number; queries: number };
};

export type Tenant = {
  id: number;
  name: string;
  slug: string;
  status: string;
  clerk_org_id: string | null;
  ai_processing_approved: boolean;
  approved_surfaces: string[];
  approved_utility_models: string[];
  created_at: string;
};

export type TenantDetail = {
  tenant: Tenant;
  brand_profile: { brand_name: string; aliases: string[]; domains: string[] } | null;
  competitors: { id: number; name: string; aliases: string[]; domains: string[] }[];
  personas: { id: number; name: string; prompt_text: string; segment_tag: string }[];
  queries: { id: number; text: string; corpus_tag: string; active: boolean }[];
  surfaces: { id: number; code: string; enabled: boolean }[];
};
