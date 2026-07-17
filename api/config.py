from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://everpresent:everpresent@localhost:5432/everpresent"
    redis_url: str = "redis://localhost:6379/0"

    # Clerk. The publishable key is public; the secret key and JWKS URL are
    # required for any authenticated route to succeed.
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""
    clerk_jwks_url: str = ""
    clerk_api_base: str = "https://api.clerk.com/v1"

    # The email that gets superadmin on seed; the Clerk user id is linked on
    # that user's first authenticated request.
    superadmin_email: str = ""

    # Raw-payload storage: "file" (VPS shared volume) or "db" (Postgres, for
    # managed hosts like Render where services can't share a disk).
    storage_backend: str = "file"
    raw_storage_dir: str = "/data/raw"

    # Measured surface: OpenAI Responses API (Mode A, §6.1). The key is a
    # deployment secret; absence disables real runs, never CI tests.
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-terra"
    openai_concurrency: int = 4
    openai_timeout_s: float = 90.0

    # Additional Mode A (API) measured surfaces. Each is a real consumer-facing
    # answer engine called over its own HTTP API — measured surfaces, not
    # utility LLM calls, so they intentionally sit outside engine/llm's
    # allowlist router (§6.1). A surface with no key configured is skipped with
    # a clear reason, never a crash. Concurrency is shared across all Mode A
    # providers via openai_concurrency.
    perplexity_api_key: str = ""
    perplexity_model: str = "sonar"
    perplexity_timeout_s: float = 90.0

    anthropic_api_key: str = ""
    # A real consumer-facing Claude model (what claude.ai serves), NOT a
    # build-time-only model. The §4 runtime-model ban is enforced by the policy
    # test, which scans this file for forbidden model substrings.
    claude_model: str = "claude-sonnet-4-6"
    claude_timeout_s: float = 90.0

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_s: float = 90.0

    # Mode B scraping (§6.2): conservative by default, sequential per surface.
    chatgpt_web_rate_per_min: float = 4.0
    chatgpt_web_headless: bool = True
    chatgpt_web_timeout_s: float = 240.0
    # Set when the container pre-installs a Chromium outside playwright's
    # bundled path.
    playwright_chromium_path: str = ""
    perplexity_web_rate_per_min: float = 4.0

    # Anti-blocking (§SCRAPING_V3). All vendor-neutral and off by default —
    # stealth hardening is free and always on; proxy and managed-browser
    # layers activate only when their env is set.
    scrape_stealth: bool = True
    # Abort image/media/font requests during scrapes — pure proxy-byte savings
    # (§SCRAPING_V3 cost), roughly halving GB/scrape. Off only if a surface
    # somehow needs media to render its answer text.
    scrape_block_assets: bool = True
    # A single proxy URL (http://user:pass@host:port). Used for any country
    # unless the map overrides it. Empty = no proxy (direct, as today).
    scrape_proxy_url: str = ""
    # JSON object mapping country code -> proxy URL, for residential
    # geo-targeting. Selection: map[country] -> proxy_url -> none.
    scrape_proxy_map: dict[str, str] = Field(default_factory=dict)
    # A managed scraping browser CDP endpoint (Layer 3). When set, adapters
    # connect over CDP instead of launching local Chromium; the provider
    # handles proxy + captcha. Use only if a surface blocks through the proxy.
    scrape_cdp_endpoint: str = ""

    # Google AIO capture (§6.3). Provider "direct" scrapes the SERP;
    # "serpapi" uses the JSON fallback when the key is set.
    google_aio_rate_per_min: float = 6.0
    google_aio_provider: str = "direct"
    google_aio_timeout_s: float = 120.0
    serpapi_key: str = ""

    # Notifications (M5): run-completion reports by email. Unset host = skip.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "reports@everpresent.local"
    smtp_starttls: bool = True

    # GA4 outcome attribution (panel #6). Reuses google_service_account_json
    # below; the SA must be granted Viewer on each tenant's GA4 property.
    # Lookback window pulled on each nightly refresh.
    ga4_lookback_days: int = 28

    # Diagnosis-twin cache (§cost): the training-only (nosearch) variant
    # measures model knowledge, which is frozen between model snapshots —
    # reuse a recent twin for the same (query, surface, model) instead of
    # re-buying it every run. 0 disables the cache (always refresh).
    diagnosis_refresh_days: int = 7

    # BigQuery mirror (§5.3). Unset project = mirror disabled.
    bigquery_project: str = ""
    bigquery_dataset: str = "everpresent_v3"
    # Path to the service-account JSON key file (mounted secret).
    google_service_account_json: str = ""
    mirror_hour_utc: int = 9


@lru_cache
def get_settings() -> Settings:
    return Settings()
