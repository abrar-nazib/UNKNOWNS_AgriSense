"""Application configuration loaded from environment via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Database ----
    DATABASE_URL: str = (
        "postgresql+asyncpg://argi:argi_dev_password@db:5432/argi"
    )

    # ---- JWT / Auth ----
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---- Billing / OTP ----
    # "mock" keeps the local demo deterministic; "bdapps" performs real
    # server-to-server OTP and subscription calls.
    BILLING_PROVIDER: str = "mock"
    MOCK_OTP_CODE: str = "1234"
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_REQUEST_COOLDOWN_SECONDS: int = 60
    BDAPPS_BASE_URL: str = "https://developer.bdapps.com"
    # Each BDApps subscription application has one provisioned tariff.
    BDAPPS_PLUS_APPLICATION_ID: str = ""
    BDAPPS_PLUS_PASSWORD: str = ""
    BDAPPS_PLUS_APPLICATION_HASH: str = ""
    BDAPPS_PRO_APPLICATION_ID: str = ""
    BDAPPS_PRO_PASSWORD: str = ""
    BDAPPS_PRO_APPLICATION_HASH: str = ""
    # Legacy single-app values remain as a temporary Plus/Pro fallback based
    # on BDAPPS_PLAN_ID, so existing deployments can migrate without downtime.
    BDAPPS_APPLICATION_ID: str = ""
    BDAPPS_PASSWORD: str = ""
    BDAPPS_APPLICATION_HASH: str = ""
    BDAPPS_PLAN_ID: str = "plus"
    BDAPPS_TIMEOUT_SECONDS: float = 15.0

    # ---- LLM: OpenRouter (default chat provider) ----
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash"
    # Cheap/fast model for narrow tasks (intent classification, extraction).
    OPENROUTER_MODEL_LITE: str = "google/gemini-2.5-flash-lite"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # ---- LLM: Ollama (optional secondary provider) ----
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_MODEL: str = "llama3.1"

    # ---- Embeddings (long-term memory table) ----
    EMBEDDINGS_PROVIDER: str = "fake"  # "fake" | "ollama" | "openai"
    EMBEDDING_DIM: int = 768
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # ---- LLM: OpenAI (embedding provider) ----
    OPENAI_API_KEY: str = ""
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"

    # ---- Knowledge base (RAG) — separate table/provider from memory ----
    # "openrouter" | "openai" | "ollama" | "fake"
    KB_EMBEDDINGS_PROVIDER: str = "openrouter"
    # OpenRouter model slug (vendor-prefixed); routed to OpenAI upstream.
    KB_EMBED_MODEL: str = "openai/text-embedding-3-small"
    KB_EMBEDDING_DIM: int = 1536  # text-embedding-3-small native dim
    KB_TOP_K: int = 5
    # Recursive chunking: ~1800 chars ≈ 450 tokens/chunk → top-5 ≈ 2.2k tokens
    # of retrieved context per tool call (decent grounding, no context blowout).
    KB_CHUNK_SIZE_CHARS: int = 1800
    KB_CHUNK_OVERLAP_CHARS: int = 200

    # ---- Agent memory tuning ----
    HISTORY_LIMIT: int = 40
    MEMORY_TOP_K: int = 5

    # ---- Logging ----
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"  # relative to the backend working dir; gitignored

    # ---- CORS ----
    # Comma-separated list of allowed origins.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
