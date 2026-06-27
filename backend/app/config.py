"""Application configuration.

Centralizes all environment-driven settings using pydantic-settings.
A single module-level ``settings`` instance is created and imported across
the app via ``from app.config import settings``.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dev fallback for the session signing secret. Used when JWT_SECRET is unset or
# explicitly blank (e.g. the empty value shipped in .env.example) so the app
# never tries to sign tokens with an empty HMAC key, which PyJWT rejects.
_DEFAULT_JWT_SECRET = "dev-insecure-jwt-secret-change-me"


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

    # --- Auth / JWT ----------------------------------------------------------
    # HS256 secret for the nba_session cookie. A dev default keeps the app
    # bootable offline; override via JWT_SECRET in any real deployment.
    jwt_secret: str = _DEFAULT_JWT_SECRET
    # Public base URL of the frontend, used to build email verification links.
    app_base_url: str = "http://localhost:3200"

    # --- AWS / SES (email, all optional) ------------------------------------
    aws_region: str = "us-east-1"
    ses_sender_email: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # --- Google OAuth (Gmail send, all optional) ----------------------------
    # Used by the integrations Google connector. All blank offline so the
    # consent flow degrades to a graceful "not configured" status.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:3200/api/auth/callback/google"

    # --- LangSmith / tracing (all optional) ----------------------------------
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None
    langsmith_tracing: bool = False
    langsmith_endpoint: str | None = None

    # Domain for the session cookie. Blank = host-only (local dev). Set to a
    # parent domain (e.g. ".niheshr.com") so the cookie is shared between the
    # frontend (aperture.niheshr.com) and the API (aperture-api.niheshr.com).
    cookie_domain: str = ""

    # --- CORS ----------------------------------------------------------------
    # Comma-separated exact origins (e.g. "http://localhost:3200,http://localhost:3001").
    cors_origins: str = "http://localhost:3200"
    # Regex matching whole origins, for wildcard subdomains. Defaults to any
    # niheshr.com subdomain over http or https (aperture.niheshr.com,
    # aperture-api.niheshr.com, ...). Override with CORS_ORIGIN_REGEX.
    cors_origin_regex: str = r"https?://([a-z0-9-]+\.)*niheshr\.com"

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _default_blank_jwt_secret(cls, value: object) -> object:
        """Coerce an unset or blank JWT secret to the dev fallback.

        PyJWT raises on an empty HMAC key, so a blank ``JWT_SECRET`` (as shipped
        in .env.example) would otherwise 500 on login. Falling back keeps the
        app bootable offline while still letting a real secret override it.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return _DEFAULT_JWT_SECRET
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated CORS origins into a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


# Module-level singleton imported throughout the application.
settings = Settings()
