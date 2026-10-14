"""Runtime configuration. All settings come from environment variables (12-factor).

Secrets (database passwords, API keys, OIDC client secrets) are injected by the
deployment platform's secret manager; nothing secret is committed to the repo.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELECTION_", env_file=".env", extra="ignore")

    environment: Environment = "development"
    # Runtime API role: subject to row-level security.
    database_url: str = "postgresql+psycopg://election_app:election_app@localhost:5432/election"
    # Worker role: BYPASSRLS, used only by background jobs that operate across tenants.
    worker_database_url: str = "postgresql+psycopg://election_worker:election_worker@localhost:5432/election"
    # Schema owner: used only by migrations and ops tooling.
    migration_database_url: str = "postgresql+psycopg://election:election@localhost:5432/election"

    # Deployed environments inject host + secrets separately (RDS-managed owner secret is JSON);
    # URLs are composed from them when present (see _compose_db_urls).
    db_host: str | None = None
    db_name: str = "election"
    db_app_password: str | None = None
    db_worker_password: str | None = None
    db_owner_secret: str | None = None

    # Raw source file storage (immutable, content addressed).
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./var/raw"
    storage_s3_bucket: str | None = None
    storage_s3_endpoint: str | None = None

    # Authentication. In production only OIDC-issued RS256/ES256 tokens are accepted.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    dev_auth_secret: str | None = None  # HS256 dev tokens; rejected outside development/test.

    # Upstream data credentials (absent => the integration is shown as unavailable).
    fec_api_key: str | None = None

    # LLM providers (provider-independent; absent => deterministic offline composer).
    llm_primary_provider: Literal["anthropic", "openai_compatible", "offline"] = "offline"
    llm_fallback_provider: Literal["anthropic", "openai_compatible", "offline"] = "offline"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: str | None = None
    openai_compatible_model: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 1200
    assistant_max_tool_calls: int = 6

    # Abuse controls.
    rate_limit_per_minute: int = 120
    assistant_rate_limit_per_minute: int = 10
    max_upload_bytes: int = 25 * 1024 * 1024

    # Survey disclosure control: cells below this unweighted n are suppressed.
    survey_min_cell_size: int = 30

    # Editorial policy: only these source keys may supply race calls.
    authorized_race_call_sources: list[str] = Field(default_factory=lambda: ["editorial-desk"])

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"
    otel_exporter_endpoint: str | None = None

    @model_validator(mode="after")
    def _compose_db_urls(self) -> Settings:
        if self.db_host:
            import json  # noqa: PLC0415
            from urllib.parse import quote  # noqa: PLC0415

            def url(user: str, pw: str) -> str:
                creds = f"{quote(user)}:{quote(pw, safe='')}"
                return f"postgresql+psycopg://{creds}@{self.db_host}:5432/{self.db_name}?sslmode=require"

            if self.db_app_password:
                self.database_url = url("election_app", self.db_app_password)
            if self.db_worker_password:
                self.worker_database_url = url("election_worker", self.db_worker_password)
            if self.db_owner_secret:
                owner = json.loads(self.db_owner_secret)
                self.migration_database_url = url(owner["username"], owner["password"])
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment in ("staging", "production"):
            if self.dev_auth_secret:
                raise ValueError("ELECTION_DEV_AUTH_SECRET must not be set in staging/production")
            if not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
                raise ValueError("OIDC issuer, audience and JWKS URL are required in staging/production")
            for url in (self.database_url, self.worker_database_url, self.migration_database_url):
                if any(f"{u}:{u}@" in url for u in ("election", "election_app", "election_worker")):
                    raise ValueError("development database credentials must not be used in staging/production")
        return self

    @property
    def allows_synthetic_data(self) -> bool:
        return self.environment in ("development", "test", "staging")


@lru_cache
def get_settings() -> Settings:
    return Settings()
