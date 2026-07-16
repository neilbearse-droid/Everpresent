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
  notify_emails: string[];
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

export type AIOSummary = {
  queries_measured: number;
  queries_with_aio: number;
  aio_share_pct: number;
  brand_cited_in_aio: number;
  source_types: Record<string, number>;
};

export type OverviewPayload = {
  brand_name: string;
  trend: { date: string; brand_score: number; competitors: Record<string, number> }[];
  share_of_voice: Record<string, number>;
  movers: { label: string; kind: string; before: number; after: number; delta: number }[];
  latest: { date: string; brand_score: number } | null;
  aio: AIOSummary;
};

export type CitationsPayload = {
  domains: { domain: string; category: string; count: number; surfaces: string[] }[];
  aio: AIOSummary;
};

export type Recommendation = {
  id: number;
  gap_ref: string;
  branch: "web_search" | "training" | "aio";
  action_text: string;
  status: "open" | "in_progress" | "done" | "dismissed" | "resolved";
  updated_at: string;
};

export type PersonasPayload = {
  date: string | null;
  segments: {
    segment: string;
    brand_score: number;
    mention_rate: number;
    citation_rate: number;
    result_count: number;
    competitor_scores: Record<string, number>;
  }[];
  trend: { date: string; segment: string; brand_score: number }[];
};

export type QueriesIntelPayload = {
  queries: {
    id: number;
    text: string;
    corpus_tag: string;
    active: boolean;
    classification: {
      surface: string;
      web_search_likelihood: string;
      signals: Record<string, number>;
      classifier_version: string;
    } | null;
    latest_results: Record<
      string,
      {
        result_id: number;
        run_id: number;
        status: string;
        mode: string;
        brand_mentioned: boolean;
      }
    >;
  }[];
};

export type EngineScorecard = {
  brand_name: string;
  engines: {
    surface: string;
    queries_measured: number;
    brand_present: number;
    brand_rate: number;
    competitor_present: number;
    top_competitor: string | null;
  }[];
  matrix: {
    id: number;
    query: string;
    corpus_tag: string;
    cells: Record<string, { state: "brand" | "competitor" | "absent"; competitors: string[] }>;
    diagnosis: { type: string; label: string; fix: string };
  }[];
  diagnosis_summary: Record<string, number>;
};

export type KpiScorecard = {
  brand_name: string;
  answer_share: number;
  share_breakdown: { name: string; share: number }[];
  prominence: {
    measured: number;
    present: number;
    presence_rate: number;
    lead_rate: number;
    avg_rank: number | null;
    position_distribution: { leads: number; second: number; third_plus: number };
  };
  sentiment: {
    counts: { positive: number; neutral: number; negative: number };
    examples: {
      positive: { query: string; surface: string; snippet: string }[];
      negative: { query: string; surface: string; snippet: string }[];
    };
  };
  head_to_head: { competitor: string; shared: number; wins: number; win_rate: number }[];
  stability: {
    series: { run_id: number; presence_rate: number }[];
    mean: number;
    swing: number;
    stdev: number;
    label: string;
  };
};

export type ActionPlan = {
  brand_name: string;
  targets: {
    domain: string;
    citations: number;
    queries: number;
    surfaces: string[];
    competitor_assoc: number;
    already_citing_you: boolean;
    example_url: string;
  }[];
  briefs: {
    query_id: number;
    query: string;
    corpus_tag: string;
    diagnosis: { type: string; label: string; fix: string };
    engines_missing: string[];
    competitors_winning: string[];
    target_sources: { domain: string; rivals: string[] }[];
    subtopics: string[];
    outline: string[];
  }[];
  summary: Record<string, number>;
};

export type TenantDetail = {
  tenant: Tenant;
  brand_profile: { brand_name: string; aliases: string[]; domains: string[] } | null;
  competitors: { id: number; name: string; aliases: string[]; domains: string[] }[];
  personas: { id: number; name: string; prompt_text: string; segment_tag: string }[];
  queries: { id: number; text: string; corpus_tag: string; active: boolean }[];
  surfaces: { id: number; code: string; enabled: boolean }[];
};
