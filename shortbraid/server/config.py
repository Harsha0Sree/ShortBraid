"""
12-Factor configuration (Day 1).

All runtime configuration is sourced from environment variables.
Nothing is hardcoded. Pydantic Settings provides:
  - Type coercion & validation
  - `.env` file support
  - Immutability after instantiation
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings — populated from env / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_env: str = Field(default="development")
    app_name: str = Field(default="shortbraid")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    # --- Postgres ---
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="shortbraid")
    postgres_password: str = Field(default="shortbraid_secret")
    postgres_db: str = Field(default="shortbraid")
    pg_pool_min: int = Field(default=5, ge=1)
    pg_pool_max: int = Field(default=20, ge=2)

    # --- Redis ---
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_password: Optional[str] = Field(default=None)
    redis_db: int = Field(default=0)
    rate_limit_rpm: int = Field(default=5, ge=1)
    cache_ttl_seconds: int = Field(default=3600, ge=1)

    # --- MinIO ---
    minio_endpoint: str = Field(default="localhost:9000")
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin")
    minio_bucket: str = Field(default="shortbraid-ingest")
    minio_secure: bool = Field(default=False)
    minio_region: str = Field(default="us-east-1")

    # --- OpenAI ---
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_chat_model: str = Field(default="gpt-4o-mini")
    openai_embed_model: str = Field(default="text-embedding-3-small")
    embed_dimensions: int = Field(default=1536)
    openai_timeout_seconds: int = Field(default=60)
    openai_max_retries: int = Field(default=3)

    # --- Worker ---
    worker_concurrency: int = Field(default=10)
    worker_max_jobs: int = Field(default=50)

    # --- Admin / Security ---
    admin_api_key: Optional[str] = Field(
        default=None, description="Admin token required in production"
    )

    # --- LLM cost (USD per 1K tokens) ---
    cost_input_per_1k: float = Field(default=0.000150)
    cost_output_per_1k: float = Field(default=0.000600)

    # --- Derived ---
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() == "production"

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        return v.upper()

    @field_validator("app_env")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        return v.lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance — pydantic_settings is heavy to construct."""
    return Settings()
