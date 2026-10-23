"""Application settings, read from environment variables (see .env.example).

This is the only module that reads configuration; other code receives a Settings object.
"""

import base64
import binascii
from functools import lru_cache
from pathlib import Path
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
    # A job not finished within its lease is assumed abandoned and handed to another worker.
    worker_lease_seconds: float = Field(default=900, gt=0)

    # Sessions (docs/ACCESS_CONTROL.md §4)
    session_idle_hours_contributor: float = Field(default=168, gt=0)
    session_idle_hours_staff: float = Field(default=12, gt=0)
    session_absolute_days: float = Field(default=30, gt=0)
    password_reset_hours: int = Field(default=24, gt=0, le=24 * 7)

    # Object storage (ADR-006). Bucket names map to app.object_store.Bucket.
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: Path = Path(".local-storage")
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = False
    bucket_quarantine: str = "lokdhara-quarantine"
    bucket_originals: str = "lokdhara-originals"
    bucket_derived: str = "lokdhara-derived"
    bucket_consent_evidence: str = "lokdhara-consent-evidence"
    bucket_exports: str = "lokdhara-exports"
    signed_url_ttl_seconds: int = Field(default=600, gt=0, le=600)

    # Recording uploads (docs/AUDIO_PROCESSING_PIPELINE.md §2)
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    uploads_per_user_per_hour: int = Field(default=60, gt=0)
    max_audio_seconds: float = Field(default=30 * 60, gt=0)
    min_audio_seconds: float = Field(default=1, ge=0)  # shorter is flagged, not rejected
    max_audio_channels: int = Field(default=2, gt=0)
    min_sample_rate_hz: int = Field(default=8000, gt=0)
    max_sample_rate_hz: int = Field(default=96000, gt=0)
    # Each ffprobe or FFmpeg run is stopped after this; keep it well under the worker lease.
    ffmpeg_timeout_seconds: float = Field(default=300, gt=0)
    # Audio uploaded to a draft that is never submitted is deleted after this (Q-T7). The
    # draft stays; the contributor's phone still has the recording and uploads it again.
    draft_upload_retention_days: int = Field(default=30, gt=0)

    # Restricted speaker identity fields (AES-256-GCM). 32 random bytes, base64-encoded.
    # In development and test a key is derived from LKD_SECRET_KEY when this is empty.
    identity_encryption_key: SecretStr | None = None

    # Consent capture (docs/CONSENT_AND_DATA_GOVERNANCE.md §3)
    consent_evidence_max_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    # People under 18 may take part, with a parent or guardian agreeing alongside them
    # (owner's decision 2026-10-23, Q-L4). Set false to stop collecting from minors.
    allow_minors: bool = True

    # Dataset releases (docs/DATASET_VERSIONING.md). Releases other than internal research
    # also need governance answers (Q-G1, Q-G5, Q-L5); until they are recorded they cannot be
    # frozen. Turn this on only once those answers are recorded.
    external_releases_enabled: bool = False
    # The data card names speakers whose share of a release's audio is above this (check D9).
    release_speaker_share_warning: float = Field(default=0.3, gt=0, le=1)
    # Export packages are deleted this long after they are built.
    export_retention_days: int = Field(default=7, gt=0)
    # The code version recorded in each frozen release; set by the deployment.
    git_commit: str = "unknown"

    # Withdrawals (docs/DATA_RETENTION_AND_DELETION.md §2). The deletion routine connects with
    # this URL as a member of app_erasure, the only role that may clear append-only rows; when
    # it is empty it uses database_url, which then must be allowed to SET ROLE app_erasure.
    erasure_database_url: str | None = None
    # Proof of consent is kept after a withdrawal until the institution says otherwise (Q-G8):
    # the recording of an oral consent stays in the consent-evidence bucket.
    withdrawal_keep_consent_evidence: bool = True

    # Prompt library media made by the team (docs/RECORDING_MODES.md)
    prompt_image_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    prompt_audio_max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # Daily digest to the maintainers (docs/OBSERVABILITY_AND_BACKUPS.md §2): counts only,
    # sent by email when a mail server and recipients are set, otherwise only logged.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, gt=0)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    digest_recipients: str = ""  # comma-separated addresses

    # Admins must sign in with a code from an authenticator app (docs/ACCESS_CONTROL.md §4).
    # Left empty it is on everywhere except development and test.
    require_admin_mfa: bool | None = None

    # Login throttling
    login_max_failures: int = Field(default=5, gt=0)
    login_max_failures_per_ip: int = Field(default=20, gt=0)
    login_window_minutes: int = Field(default=15, gt=0)
    login_lockout_minutes: int = Field(default=15, gt=0)

    # Public sign-up (ADR-028): anyone may make a contributor account. Facilitators often sign
    # people up on one shared network, so the per-network limit is generous.
    open_signup: bool = True
    signup_max_per_ip: int = Field(default=20, gt=0)
    signup_window_minutes: int = Field(default=60, gt=0)

    @property
    def is_local(self) -> bool:
        return self.env in ("development", "test")

    @property
    def cookie_secure(self) -> bool:
        """Cookies carry the Secure flag everywhere except local http development."""
        return not self.is_local

    @property
    def admin_mfa_required(self) -> bool:
        return self.require_admin_mfa if self.require_admin_mfa is not None else not self.is_local

    @property
    def digest_recipient_list(self) -> list[str]:
        return [a.strip() for a in self.digest_recipients.split(",") if a.strip()]

    @property
    def effective_migration_url(self) -> str:
        return self.migration_database_url or self.database_url

    @model_validator(mode="after")
    def _require_real_secret_outside_local(self) -> "Settings":
        secret = self.secret_key.get_secret_value()
        if not self.is_local and (secret == LOCAL_ONLY_SECRET or len(secret) < 32):
            raise ValueError("LKD_SECRET_KEY must be a random value of at least 32 characters")
        if not self.is_local and self.identity_encryption_key is None:
            raise ValueError("LKD_IDENTITY_ENCRYPTION_KEY is required outside development and test")
        if self.identity_encryption_key is not None:
            self.identity_key_bytes()  # fail at startup, not on the first identity write
        return self

    def identity_key_bytes(self) -> bytes | None:
        """The 32-byte identity key, or None when it should be derived (development and test)."""
        if self.identity_encryption_key is None:
            return None
        try:
            key = base64.b64decode(self.identity_encryption_key.get_secret_value(), validate=True)
        except binascii.Error as exc:
            raise ValueError("LKD_IDENTITY_ENCRYPTION_KEY must be base64") from exc
        if len(key) != 32:
            raise ValueError("LKD_IDENTITY_ENCRYPTION_KEY must decode to 32 bytes")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
