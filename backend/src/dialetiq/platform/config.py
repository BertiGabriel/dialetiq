"""Application configuration. Values come from the environment, never from code."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DIALETIQ_", extra="ignore")

    environment: str = "development"

    # Application traffic uses Neon's POOLED endpoint (`-pooler` in the host).
    # Migrations use the direct one -- PgBouncer in transaction mode does not
    # support the session-level state Alembic relies on.
    database_url: str = Field(
        default="postgresql+psycopg://dialetiq:dialetiq@localhost:5432/dialetiq",
    )
    migration_database_url: str | None = None

    redis_url: str = "redis://localhost:6379/0"

    # Session cookie signing. Rotating this logs everyone out, which is the
    # intended behaviour after a compromise.
    session_secret: str = Field(default="dev-only-do-not-use-in-production")

    # Peppers consumer phone/email hashes so a database dump alone cannot be
    # brute-forced back to real people. Brazilian mobile numbers span ~10^9
    # values and HMAC-SHA256 is fast: a leaked pepper alongside a dump makes the
    # entire consumer base reidentifiable in minutes.
    #
    # In production this comes from the secret manager and NOTHING ELSE.
    identity_pepper: str = Field(default="dev-only-do-not-use-in-production")


settings = Settings()
