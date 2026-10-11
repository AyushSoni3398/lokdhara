import pytest

from app.config import Settings


def test_settings_read_lkd_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LKD_ENV", "test")
    monkeypatch.setenv("LKD_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    settings = Settings(_env_file=None)
    assert settings.env == "test"
    assert settings.database_url.endswith("@db:5432/x")


def test_secret_key_is_not_revealed_in_repr() -> None:
    settings = Settings(_env_file=None, secret_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ValueError, match="LKD_SECRET_KEY"):
        Settings(_env_file=None, env="production")


def test_production_accepts_long_random_secret_and_secure_cookies() -> None:
    settings = Settings(_env_file=None, env="production", secret_key="x" * 40)
    assert settings.cookie_secure
    assert not Settings(_env_file=None, env="development").cookie_secure


def test_migrations_fall_back_to_app_database_url() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://a@h/d")
    assert settings.effective_migration_url == "postgresql+psycopg://a@h/d"
