from functools import lru_cache

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

    # Object storage root for raw response payloads (VPS volume).
    raw_storage_dir: str = "/data/raw"

    # Measured surface: OpenAI Responses API (Mode A, §6.1). The key is a
    # deployment secret; absence disables real runs, never CI tests.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_concurrency: int = 4
    openai_timeout_s: float = 90.0

    # Mode B scraping (§6.2): conservative by default, sequential per surface.
    chatgpt_web_rate_per_min: float = 4.0
    chatgpt_web_headless: bool = True
    chatgpt_web_timeout_s: float = 240.0
    # Set when the container pre-installs a Chromium outside playwright's
    # bundled path.
    playwright_chromium_path: str = ""
    perplexity_web_rate_per_min: float = 4.0

    # Notifications (M5): run-completion reports by email. Unset host = skip.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "reports@everpresent.local"
    smtp_starttls: bool = True

    # BigQuery mirror (§5.3). Unset project = mirror disabled.
    bigquery_project: str = ""
    bigquery_dataset: str = "everpresent_v3"
    # Path to the service-account JSON key file (mounted secret).
    google_service_account_json: str = ""
    mirror_hour_utc: int = 9


@lru_cache
def get_settings() -> Settings:
    return Settings()
