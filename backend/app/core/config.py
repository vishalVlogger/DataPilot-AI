from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DataPilot AI"
    environment: str = "development"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
