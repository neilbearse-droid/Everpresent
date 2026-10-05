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
  let res: Response;
  try {
    res = await fetch(`${API_ORIGIN}${path}`, {
      ...init,
      headers: {
        ...(init.headers ?? {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      cache: "no-store",
    });
  } catch (e) {
    // API down / DNS / reset: a failed result, never an uncaught page crash.
    return { ok: false, status: 0, data: null, error: `API unreachable (${String(e)})` };
  }
  let data: T | null = null;
  let error: string | null = null;
  const body = await res.text();
  try {
    const parsed = body ? JSON.parse(body) : null;
    if (res.ok) {
      data = parsed as T;
    } else {
      error = describeError(parsed?.detail) ?? (body || `HTTP ${res.status}`);
    }
  } catch {
    error = res.ok ? null : body || `HTTP ${res.status}`;
  }
  return { ok: res.ok, status: res.status, data, error };
}

/** FastAPI error detail → readable text: a string as-is, a 422 validation
 * list as its joined messages. */
function describeError(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : null))
      .filter(Boolean);
    return msgs.length ? msgs.join("; ") : null;
  }
  return null;
}

/** Build the ?start=&end= suffix for time-scoped intel endpoints from the
 * page's ?from=&to= search params (the DateRange picker's URL state). */
export function rangeQuery(from?: string, to?: string): string {
  const p = new URLSearchParams();
  if (from) p.set("start", from);
  if (to) p.set("end", to);
  const qs = p.toString();
  return qs ? `?${qs}` : "";
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
  ga4_property_id: string | null;
  plan: string;
  fanout_reprobe_enabled: boolean;
  entity_extraction_enabled: boolean;
  aio_geo: { gl?: string; hl?: string } | null;
  created_at: string;
};

export type PlanLimits = {
  label: string;
  max_prompts: number | null;
  max_personas: number | null;
  max_engines: number | null;
  diagnosis: boolean;
  model_tier: string;
  outcome: boolean;
  max_runs_per_day: number | null;
  monthly_price_usd: number;
  shard_probes_per_prompt: number;
  shard_probes_per_run: number;
};

export type OutcomePayload = {
  brand_name: string;
  connected: boolean;
  has_data: boolean;
  series: { date: string; sessions: number; conversions: number; brand_score: number | null }[];
  engine_totals: { engine: string; sessions: number; conversions: number }[];
  totals: { sessions: number; conversions: number };
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
  status: "ok" | "error" | "blocked";
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

/** Citability fingerprint of a page. Tier-1 = evidence-based citation levers;
 * the rest are machine-legibility hygiene. Fields are optional because pages
 * crawled before the M5 upgrade only carry the hygiene keys. */
export type PageFeatures = {
  quotation_count?: number;
  statistic_count?: number;
  data_point_density?: number;
  has_answer_capsule?: boolean;
  front_loaded?: boolean;
  citation_count?: number;
  promotional_tone_score?: number;
  json_ld: boolean;
  faq_schema: boolean;
  has_tables: boolean;
  recent_year_mentions: number;
  word_count: number;
};

export type OverviewPayload = {
  brand_name: string;
  trend: { date: string; brand_score: number; competitors: Record<string, number> }[];
  share_of_voice: Record<string, number>;
  movers: { label: string; kind: string; before: number; after: number; delta: number }[];
  latest: { date: string; brand_score: number } | null;
  aio: AIOSummary;
  /** Provider changes inside the trend window (absent on an older API). */
  series_notes?: { date: string; surface: string; note: string }[];
  /** Pooled mention rate with its 95% range (absent on an older API). */
  mention_rate?: MentionRate;
  /** What changed that needs action (absent on an older API). */
  alerts?: { severity: "high" | "medium" | "good"; kind: string; text: string }[];
};

export type EngineMode = {
  surface: string;
  label: string;
  mode: "retrieve" | "recall" | "mixed";
  search_rate: number;
  avg_fanout: number | null;
  measured: number;
  from_probe: boolean;
  standing_value: number;
  standing_unit: "cited" | "named";
  standing_label: string;
  named_rate: number;
  cited_rate: number;
  blurb: string;
  play: string;
};

export type EngineModesPayload = {
  brand_name: string;
  engines: EngineMode[];
  modes: {
    recall: { visibility: number; answers: number };
    retrieval: { visibility: number; answers: number };
  };
  composite: { score: number; date: string } | null;
  observed: boolean;
};

export type FanoutShard = {
  id: number | null;
  // Vs this shard's previous re-probe (M25c); null on its first measurement.
  trend: "won_back" | "lost" | "steady" | null;
  text: string;
  engines: string[];
  names_brand: boolean;
  names_competitors: string[];
  // Per-shard presence — only set when source is "reprobed" (M25b).
  brand_present: boolean | null;
  winners: string[];
  source: "reprobed" | "unresolved";
  priority: "high" | "med" | "low" | "";
  probe_status: string;
  probe_engine: string | null;
  probed_at: string | null;
};

export type FanoutScorecardPayload = {
  brand_name: string;
  observed: boolean;
  branded_excluded: boolean;
  prompts: {
    query: string;
    shards_total: number;
    engines_count: number;
    reach_by_engine: Record<string, number>;
    brand_in_answer: boolean;
    contested: number;
    shards_present: number;
    shards_absent: number;
    shards_unresolved: number;
    high_misses: number;
    won_back: number;
    lost: number;
    shards: FanoutShard[];
  }[];
  coverage: { reprobed: number; unresolved: number };
  trend: { won_back: number; lost: number };
  reprobe_enabled: boolean;
};

export type CitationsPayload = {
  domains: { domain: string; category: string; count: number; surfaces: string[] }[];
  power_pages: {
    url: string;
    domain: string;
    category: string;
    citations: number;
    queries: number;
    surfaces: string[];
    on_page: boolean | null;
    competitors_on_page: string[];
    page_features: PageFeatures | null;
  }[];
  consulted_domains: { domain: string; count: number; queries: number }[];
  source_types_by_engine: Record<string, Record<string, number>>;
  aio: AIOSummary;
};

export type Recommendation = {
  id: number;
  gap_ref: string;
  branch: string;
  title: string;
  action_text: string;
  priority: number;
  evidence: "official" | "strong" | "moderate" | "emerging" | "";
  why: string;
  steps: string[] | null;
  query_text: string;
  link: string;
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
    branded: boolean;
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
    brand_cited: number;
    citation_rate: number;
    mention_citation_gap: number;
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

export type RateChange = {
  verdict: "up" | "down" | "no real change" | "not enough data";
  delta: number | null;
  p_value: number | null;
};

export type MentionRate = {
  rate: number;
  low: number;
  high: number;
  answers: number;
  mentioned: number;
  prompts: number;
  change: RateChange;
};

export type MentionRates = {
  window: { start: string; end: string; split: string };
  overall: MentionRate;
  engines: (MentionRate & { surface: string; label: string })[];
};

export type KpiScorecard = {
  brand_name: string;
  /** Headline: pooled mention rate with 95% ranges (absent on an older API). */
  mention_rates?: MentionRates;
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
    subtopics_source?: "observed" | "heuristic";
    outline: string[];
    /** Set when the query invites a self-ranked list (spam-policy risk). */
    spam_risk?: { level: string; note: string } | null;
    contestability: {
      score: number | null;
      label: string;
      volatility: number | null;
      dependence: number;
    };
    intervention: { id: number; shipped_at: string; url: string } | null;
    citability: {
      ready: boolean;
      winners?: string[];
      spec?: {
        quotations: boolean;
        statistic_count: number;
        has_answer_capsule: boolean;
        front_loaded: boolean;
        citation_count: number;
        promotional_tone_score: number;
        json_ld: boolean;
        faq_schema: boolean;
        has_tables: boolean;
        recent_year_mentions: number;
        word_count: number;
      };
      your_page?: { url: string; features: Record<string, unknown> } | null;
      gaps?: string[];
    };
  }[];
  strike_zone: Record<string, number>;
  protect: {
    ready: boolean;
    lost: { url: string; domain: string; queries: string[]; still_cited_on: number }[];
    held: number;
    gained: number;
  };
  summary: Record<string, number>;
};

export type InterventionsReport = {
  interventions: {
    id: number;
    query: string;
    description: string;
    url: string;
    shipped_at: string;
    created_by: string;
    before_rate: number | null;
    after_rate: number | null;
    delta: number | null;
    control_delta: number | null;
    newly_visible: string[];
    awaiting: boolean;
  }[];
  aggregate: {
    measured: number;
    avg_delta: number;
    avg_control_delta: number | null;
  } | null;
};

export type RoutingReport = {
  brand_name: string;
  observed: boolean;
  engines: {
    surface: string;
    measured: number;
    searched: number;
    search_rate: number;
    from_probe: boolean;
  }[];
  prompts: { query: string; engines: Record<string, boolean> }[];
};

export type ContentDraft = {
  id: number;
  source_kind: string;
  source_ref: string;
  title: string;
  body: string;
  model: string;
  status: string;
  updated_at: string;
};

export type AccuracyReport = {
  brand_name: string;
  facts_on_file: number;
  measured: number;
  error_count: number;
  errors: {
    fact_id: number;
    subject: string;
    category: string;
    severity: string;
    expected: string;
    stated: string;
    detail: string;
    snippet: string;
    engines: string[];
  }[];
};

export type BrandReport = {
  brand_name: string;
  queries_tracked: number;
  measured: number;
  presence_rate: number;
  sentiment: Record<string, number>;
  accuracy_issues: number;
  observed: boolean;
  queries: {
    query: string;
    surfaces: {
      surface: string;
      present: boolean;
      sentiment: string | null;
      snippet: string;
    }[];
    accuracy: {
      subject: string;
      stated: string;
      expected: string;
      detail: string;
      engine: string;
    }[];
  }[];
};

export type WhitespaceReport = {
  brand_name: string;
  measured: number;
  entity_count: number;
  observed: boolean;
  entities: {
    name: string;
    count: number;
    segments: string[];
    engines: string[];
  }[];
};

export type FanoutReport = {
  brand_name: string;
  observed: boolean;
  prompts: {
    query: string;
    count: number;
    subqueries: { text: string; engines: string[] }[];
  }[];
};

export type AccessAuditAgent = {
  agent: string;
  role: string;
  kind: string;
  allowed: boolean;
  mentioned: boolean;
};

export type AccessRendering = {
  verdict: "pass" | "warn" | "fail";
  word_count: number;
  reason: string;
  signals: { mount_node?: boolean; noscript_warning?: boolean; script_heavy?: boolean };
};

export type AccessAuditDomain = {
  domain: string;
  error: string | null;
  robots_status: number | null;
  agents: AccessAuditAgent[];
  has_llms_txt: boolean;
  has_json_ld: boolean;
  status_normal: number | null;
  status_bot: number | null;
  ua_blocked: boolean;
  rendering: AccessRendering;
  entity: {
    has_sameas: boolean;
    has_org_schema: boolean;
    links_wikipedia: boolean;
    links_wikidata: boolean;
  };
  grade: "pass" | "warn" | "fail";
  issues: string[];
};

export type EngineReadiness = {
  code: string;
  label: string;
  mode: "API" | "Browser" | "SERP";
  available: boolean;
  on: boolean;
  needs: string[];
  verdict:
    | "ready" | "unavailable" | "off" | "outside_plan" | "not_run_yet"
    | "missing_key" | "blocked" | "error" | "withheld"
    | "check_ok" | "check_failed" | "check_parse";
  hint: string;
  last_run: { run_id: number | null; at: string | null; ok: number; blocked: number; error: number };
  /** Latest live engine check (absent on an older API). */
  check?: {
    status: string;
    at: string;
    latency_ms: number;
    model: string;
    citations: number;
    detail: string;
  } | null;
};

export type ReadinessPayload = {
  engines: EngineReadiness[];
  checks: { label: string; ok: boolean; hint: string }[];
  /** Database, Redis, workers, scheduler (absent on an older API). */
  system?: { label: string; ok: boolean; hint: string }[];
};

export type TenantDetail = {
  tenant: Tenant;
  brand_profile: { brand_name: string; aliases: string[]; domains: string[] } | null;
  competitors: { id: number; name: string; aliases: string[]; domains: string[] }[];
  personas: { id: number; name: string; prompt_text: string; segment_tag: string }[];
  queries: { id: number; text: string; corpus_tag: string; active: boolean; branded: boolean }[];
  surfaces: { id: number; code: string; enabled: boolean }[];
  plans: Record<string, PlanLimits>;
};

export type AgentPage = {
  path: string;
  hits: number;
  user: number;
  search: number;
  training: number;
  agent: number;
  errors: number;
  cited: number;
};

export type AgentAnalytics =
  | { has_data: false; days: number }
  | {
      has_data: true;
      days: number;
      total_hits: number;
      verified_share: number;
      error_rate: number;
      by_purpose: Record<"search" | "user" | "agent" | "training", number>;
      by_company: { company: string; hits: number }[];
      by_bot: {
        bot: string;
        company: string;
        purpose: string;
        hits: number;
        verified: number;
        errors: number;
      }[];
      series: { date: string; search: number; user: number; agent: number; training: number }[];
      top_pages: AgentPage[];
      user_fetch_pages: AgentPage[];
      read_not_cited: AgentPage[];
      cited_at_risk: { path: string; cited: number; reason: string }[];
      broken_pages: AgentPage[];
      pages_tracked: number;
    };

export type RateSummary = { rate: number; low: number; high: number; answers: number; mentioned: number };

export type AnswerShape =
  | { has_data: false; days: number }
  | {
      has_data: true;
      days: number;
      engines: {
        surface: string;
        label: string;
        model: string;
        answers: number;
        logged_in: boolean | null;
        first_seen: string;
        last_seen: string;
        search_rate: number;
        search_rate_source: string;
        citations_per_answer: number;
        inline_share: number;
        own_share: number;
        third_party_share: number;
        rival_share: number;
        mention: RateSummary;
        mentioned_unlinked_share: number;
        model_note: string;
      }[];
      model_changes: { surface: string; label: string; model: string; since: string }[];
      current_models: Record<string, string>;
      memory_vs_search: {
        surface: string;
        label: string;
        memory: RateSummary | null;
        search: RateSummary | null;
        verdict: string;
      }[];
      perception: {
        sentences: number;
        themes: {
          theme: string;
          mentions: number;
          objections: number;
          memory: number;
          search: number;
          examples: string[];
        }[];
      };
    };

export type OwnPages = {
  days: number;
  domains: string[];
  has_logs: boolean;
  has_first_party: boolean;
  pages_total: number;
  flagged: number;
  pages: {
    path: string;
    url: string | null;
    cited: number;
    inline: number;
    engines: string[];
    crawl: {
      status: string;
      http_status: number | null;
      checked: string | null;
      has_updated_date: boolean;
      latest_year: number;
      has_price: boolean;
    } | null;
    fact_conflicts: { subject: string; expected: string; stated: string; snippet: string }[];
    bot_reads: number;
    bot_errors: number;
    first_party: Record<string, number>;
    flags: string[];
  }[];
  in_ai_features_not_sampled: { path: string; first_party: Record<string, number> }[];
};

export type FirstPartySummary = {
  available: Record<string, string>;
  sources: { source: string; label: string; metric: string; total: number; from: string | null; to: string | null; rows: number }[];
};

export type SamplePlan = {
  runs_per_week: number;
  target_change_pts: number;
  window_days: number;
  summary: string;
  engines: {
    surface: string;
    label: string;
    baseline_rate: number;
    answers_per_run: number;
    answers_per_half_window: number;
    needed_per_half_window: number;
    detectable_change_pts: number | null;
    can_detect_target: boolean;
    ready_by: string | null;
    more_answers_needed_x: number | null;
    too_few_to_plan?: boolean;
  }[];
};

export type Briefing = {
  brand: string;
  winning: {
    verdict: "gaining" | "losing" | "holding" | "baseline" | "unknown";
    line: string;
    rate: number | null;
    low: number | null;
    high: number | null;
    answers: number;
    top_rival: { name: string; share: number } | null;
  };
  why: { kind: string; tone: string; text: string }[];
  this_week: {
    id: number;
    title: string;
    kind: string;
    evidence: string;
    why: string;
    link: string;
    status: string;
  }[];
  focus: string | null;
};

export type PickSummary = {
  first_pick: RateSummary;
  named: RateSummary;
  no_pick: number;
  top_rival: { name: string; rate: number } | null;
  leader: string | null;
};

export type AgentPicks = {
  has_prompts: boolean;
  has_data: boolean;
  brand: string;
  days?: number;
  overall?: PickSummary;
  kinds: ({ kind: string } & PickSummary)[];
  engines: ({ surface: string; label: string } & PickSummary)[];
  prompts: ({ text: string; kind: string } & PickSummary)[];
};

export type ProofSignal = {
  key: string;
  label: string;
  kind: "rate" | "count" | "context";
  before: number | null;
  after: number | null;
  before_n?: number;
  after_n?: number;
  delta_pts?: number | null;
  control_delta_pts?: number | null;
  net_pts?: number | null;
  change_pct?: number | null;
  control_change_pct?: number | null;
  verdict: string;
  note: string;
};

export type Proof = {
  window_days: number;
  summary: string | null;
  items: {
    id: number;
    query: string;
    description: string;
    url: string;
    path: string;
    shipped_at: string;
    window_days: number;
    status: "proven" | "early" | "no_change" | "worse" | "awaiting";
    headline: string;
    signals: ProofSignal[];
  }[];
};

export type AdsReport = {
  brand: string;
  days: number;
  has_data: boolean;
  answers: number;
  units: number;
  brand_share: number;
  engines: { surface: string; label: string; answers: number; with_ads: number; ad_rate: number }[];
  advertisers: { name: string; type: string; units: number; share: number; example: string }[];
};
