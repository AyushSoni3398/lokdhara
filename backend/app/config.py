"""Application settings, read from environment variables (see .env.example).

This is the only module that reads configuration; other code receives a Settings object.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ONLY_SECRET = "change-me-local-only"  # noqa: S105 - placeholder, rejected outside dev/test


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LKD_",
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "staging", "production"] = "development"
    base_url: str = "http://localhost:5173"
    secret_key: SecretStr = SecretStr(LOCAL_ONLY_SECRET)
    database_url: str = "postgresql+psycopg://lokdhara:lokdhara@localhost:5432/lokdhara"
    # Migrations run as the schema owner; the app should run as a member of app_rw.
    migration_database_url: str | None = None
    log_level: str = "INFO"
    worker_poll_seconds: float = Field(default=5.0, gt=0)

    # Sessions (docs/ACCESS_CONTROL.md §4)
    session_idle_hours_contributor: float = Field(default=168, gt=0)
    session_idle_hours_staff: float = Field(default=12, gt=0)
    session_absolute_days: float = Field(default=30, gt=0)
    password_reset_hours: int = Field(default=24, gt=0, le=24 * 7)

    # Login throttling
    login_max_failures: int = Field(default=5, gt=0)
    login_max_failures_per_ip: int = Field(default=20, gt=0)
    login_window_minutes: int = Field(default=15, gt=0)
    login_lockout_minutes: int = Field(default=15, gt=0)

    @property
    def is_local(self) -> bool:
        return self.env in ("development", "test")

    @property
    def cookie_secure(self) -> bool:
        """Cookies carry the Secure flag everywhere except local http development."""
        return not self.is_local

    @property
    def effective_migration_url(self) -> str:
        return self.migration_database_url or self.database_url

    @model_validator(mode="after")
    def _require_real_secret_outside_local(self) -> "Settings":
        secret = self.secret_key.get_secret_value()
        if not self.is_local and (secret == LOCAL_ONLY_SECRET or len(secret) < 32):
            raise ValueError("LKD_SECRET_KEY must be a random value of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
