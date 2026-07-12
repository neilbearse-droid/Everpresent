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
  monthly_spend_cap_usd: number;
  created_at: string;
};

export type Run = {
  id: number;
  trigger: string;
  status: "pending" | "running" | "complete" | "failed" | "gated" | "capped";
  surface_set: string[];
  mode_set: string[];
  started_at: string | null;
  finished_at: string | null;
  cost_usd: number;
  counts: Record<string, number>;
  error: string | null;
  created_at: string;
};

export type RunResult = {
  id: number;
  query_text: string;
  persona_name: string;
  persona_segment: string;
  surface: string;
  mode: string;
  status: "ok" | "error";
  error: string | null;
  latency_ms: number;
  response_hash: string;
};

export type RunDetail = {
  run: Run;
  results: { result: RunResult; citations: { url: string; domain: string }[] }[];
};

export type AdminRunsPayload = {
  runs: Run[];
  month_spend_usd: number;
  monthly_spend_cap_usd: number;
};

export type RawEnvelope = {
  surface: string;
  mode: string;
  query: string;
  persona: string;
  persona_prompt: string;
  model: string;
  parsed_text: string;
  cost_usd: number;
  response: unknown;
};

export type TenantDetail = {
  tenant: Tenant;
  brand_profile: { brand_name: string; aliases: string[]; domains: string[] } | null;
  competitors: { id: number; name: string; aliases: string[]; domains: string[] }[];
  personas: { id: number; name: string; prompt_text: string; segment_tag: string }[];
  queries: { id: number; text: string; corpus_tag: string; active: boolean }[];
  surfaces: { id: number; code: string; enabled: boolean }[];
};
