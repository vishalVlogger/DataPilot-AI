from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DataPilot AI"
    app_version: str = "0.6.0-beta"
    environment: str = "development"
    app_env: str = "development"
    ai_provider: str = "mock"
    max_upload_size_mb: int = 25
    max_rows: int = 250_000
    max_columns: int = 500
    max_ai_sample_rows: int = 100
    max_chart_rows: int = 100
    max_category_analysis: int = 100
    max_quality_examples: int = 5
    semantic_year_min: int = 1900
    semantic_year_tolerance: int = 2
    high_cardinality_min_unique: int = 5
    high_cardinality_ratio: float = 0.5
    pandas_row_threshold: int = 50_000
    duckdb_row_threshold: int = 50_000
    max_analysis_rows: int = 1_000_000
    forced_execution_engine: str | None = None
    data_storage_dir: Path = Path(".data")
    dataset_storage_root: Path | None = None
    parquet_compression: str = "zstd"
    database_url: str = "sqlite:///./datapilot.db"
    enable_pdf_reports: bool = True
    background_jobs_enabled: bool = True
    secret_key: str = "development-only-change-me-32-bytes-minimum"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    refresh_cookie_name: str = "datapilot_refresh"
    default_plan: str = "free"
    frontend_url: str = "http://localhost:3000"
    rate_limit_enabled: bool = True
    rate_limit_backend: str = "memory"
    redis_url: str | None = None
    email_provider: str = "console"
    email_from: str = "DataPilot AI <no-reply@datapilot.local>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_verification_expire_hours: int = 24
    password_reset_expire_minutes: int = 60
    invitation_expire_days: int = 7
    sentry_dsn: str | None = None
    job_execution_mode: str = "local"
    dataset_storage_backend: str = "local"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str | None = None
    activity_retention_days: int = 180
    job_retention_days: int = 90
    refresh_session_retention_days: int = 30
    report_retention_days: int = 90
    feature_workspace_invites: bool = True
    feature_pdf_reports: bool = True
    feature_external_ai: bool = True
    feature_s3_storage: bool = False
    registration_mode: str = "open"
    beta_registration_enabled: bool = True
    beta_max_users: int | None = None
    beta_notice: str = "DataPilot is in beta. Avoid sensitive or regulated data unless approved, and review analytical results before relying on them."
    legacy_workspace_id: str = "00000000-0000-0000-0000-000000000001"
    legacy_user_id: str = "00000000-0000-0000-0000-000000000001"
    cors_origins: str = "http://localhost:3000"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    ai_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def storage_root(self) -> Path:
        return self.dataset_storage_root or self.data_storage_dir

    @property
    def secure_cookies(self) -> bool:
        return (self.app_env or self.environment).lower() in {"production", "staging"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
