"""
core/config.py — Application settings via pydantic-settings.

All configuration is read from environment variables or a .env file.
No secrets in source code.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import List, Literal

from pydantic import AnyHttpUrl, EmailStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "Original"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "testing", "staging", "production"] = "development"
    DEBUG: bool = False

    # ── API ──────────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    _ALLOWED_ORIGINS_STR: str = (
        "http://localhost:3000,http://localhost:8080,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )
    
    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        """Parse comma-separated origins string into list."""
        if isinstance(self._ALLOWED_ORIGINS_STR, str):
            return [o.strip() for o in self._ALLOWED_ORIGINS_STR.split(",")]
        return self._ALLOWED_ORIGINS_STR

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY: str = secrets.token_urlsafe(64)  # MUST be overridden in production
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 chars in production")
            if "CHANGE_ME" in self.SECRET_KEY or self.SECRET_KEY == "":
                raise ValueError(
                    "SECRET_KEY still contains placeholder. Generate one with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )
            if self.FIRST_ADMIN_PASSWORD in ("changeme123!", "CHANGE_ME_USE_A_STRONG_PASSWORD", ""):
                raise ValueError("FIRST_ADMIN_PASSWORD must be changed from default in production")
            if "CHANGE_ME" in self.DATABASE_URL:
                raise ValueError("DATABASE_URL still contains placeholder — set a real password")
            if self.CANVAS_WEBHOOK_SECRET and "CHANGE_ME" in self.CANVAS_WEBHOOK_SECRET:
                raise ValueError("CANVAS_WEBHOOK_SECRET still contains placeholder")

            # Validate CORS origins: production must not use only localhost
            allowed_origins = self.ALLOWED_ORIGINS
            localhost_origins = {o for o in allowed_origins if 'localhost' in o.lower() or '127.0.0.1' in o}

            # If all origins are localhost (or empty), raise an error
            if not allowed_origins or all('localhost' in o.lower() or '127.0.0.1' in o for o in allowed_origins):
                raise ValueError(
                    "ALLOWED_ORIGINS is not configured for production. "
                    "Set _ALLOWED_ORIGINS_STR environment variable to your real domain(s) "
                    "(e.g., 'https://example.com,https://www.example.com'). "
                    "Localhost-only origins will block all browser traffic in production."
                )
        return self

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://original:original@localhost:5432/original_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600  # seconds

    # ── Redis (cache + task queue) ────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL_SECONDS: int = 3600  # feature vector cache TTL

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: str = "60/minute"
    RATE_LIMIT_SCORING: str = "10/minute"   # compute-heavy
    RATE_LIMIT_AUTH: str = "5/minute"       # brute-force protection

    # ── ML model ─────────────────────────────────────────────────────────────
    MODEL_VERSION: str = "1.0.0"
    MIN_BASELINE_SAMPLES: int = 3           # below this → insufficient confidence
    MIN_BASELINE_FOR_ESCALATE: int = 5      # below this → suppress escalate action

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_JSON: bool = True  # False for development readability

    # ── First-run admin ───────────────────────────────────────────────────────
    FIRST_ADMIN_EMAIL: EmailStr = "admin@original.seminary"  # type: ignore[assignment]
    FIRST_ADMIN_PASSWORD: str = "changeme123!"

    # ── Feature flags ─────────────────────────────────────────────────────────
    ENABLE_BACKGROUND_SCORING: bool = True
    ENABLE_REDIS_CACHE: bool = False  # disabled until Redis is provisioned
    ENABLE_METRICS: bool = True       # set to False to suppress /metrics endpoint

    # ── Canvas / LTI 1.3 ──────────────────────────────────────────────────────
    # Base URL for this Original instance (used in LTI redirect URIs and report links)
    ORIGINAL_BASE_URL: str = "http://localhost:8000"

    # Canvas instance base URL (e.g. https://canvas.instructure.com)
    CANVAS_BASE_URL: str = "https://canvas.instructure.com"

    # System-level Canvas API token (optional — per-submission tokens preferred)
    CANVAS_API_TOKEN: str = ""

    # HMAC-SHA256 secret Canvas uses to sign webhook payloads
    CANVAS_WEBHOOK_SECRET: str = ""

    # LTI privacy level: "private" (no PII) or "public" (email + name + SIS ID)
    # "private" is the default — instructors identify students by Canvas context
    LTI_PRIVACY_LEVEL: str = "private"

    # ── Data retention defaults (overridable per-institution via admin API) ────
    # 0 = no automatic deletion; set to e.g. 365 for 1-year rolling retention
    DEFAULT_RETENTION_DAYS: int = 0
    # False = submissions are never indexed into a global comparison corpus
    DEFAULT_INDEX_SUBMISSIONS: bool = False


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call get_settings() anywhere."""
    return Settings()
