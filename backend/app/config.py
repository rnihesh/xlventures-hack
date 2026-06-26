"""Application configuration.

Centralizes all environment-driven settings using pydantic-settings.
A single module-level ``settings`` instance is created and imported across
the app via ``from app.config import settings``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration read from environment variables and an optional .env file.

    Every field has a sensible default so the walking skeleton can boot without
    any external services configured (no database, no real OpenAI key).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    app_env: str = "development"
    app_name: str = "nba-backend"

    # --- OpenAI / LLM --------------------------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None

    # --- Database (optional) -------------------------------------------------
    # When unset the app runs in DB-less mode (in-memory checkpointer, no pool).
    database_url: str | None = None

    # --- LangSmith / tracing (all optional) ----------------------------------
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None
    langsmith_tracing: bool = False
    langsmith_endpoint: str | None = None

    # --- CORS ----------------------------------------------------------------
    # Comma-separated list in env (e.g. "http://localhost:3000,http://localhost:3001").
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated CORS origins into a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


# Module-level singleton imported throughout the application.
settings = Settings()
