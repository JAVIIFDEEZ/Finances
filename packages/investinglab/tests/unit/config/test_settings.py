from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from investinglab.config import Environment, LogFormat, LogLevel, Settings, get_settings


def test_defaults_are_safe_for_local_development() -> None:
    settings = Settings()

    assert settings.environment is Environment.LOCAL
    assert settings.log_level is LogLevel.INFO
    assert settings.data_dir == Path("data")
    assert settings.effective_log_format is LogFormat.CONSOLE


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTINGLAB_ENVIRONMENT", "production")
    monkeypatch.setenv("INVESTINGLAB_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("INVESTINGLAB_DATA_DIR", "/srv/investinglab")

    settings = Settings()

    assert settings.environment is Environment.PRODUCTION
    assert settings.log_level is LogLevel.WARNING
    assert settings.data_dir == Path("/srv/investinglab")


def test_reads_dotenv_file_in_working_directory() -> None:
    Path(".env").write_text("INVESTINGLAB_ENVIRONMENT=staging\n", encoding="utf-8")

    assert Settings().environment is Environment.STAGING


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        (Environment.LOCAL, LogFormat.CONSOLE),
        (Environment.TEST, LogFormat.JSON),
        (Environment.STAGING, LogFormat.JSON),
        (Environment.PRODUCTION, LogFormat.JSON),
    ],
)
def test_log_format_defaults_to_json_outside_local(
    environment: Environment, expected: LogFormat
) -> None:
    assert Settings(environment=environment).effective_log_format is expected


def test_explicit_log_format_wins() -> None:
    settings = Settings(environment=Environment.PRODUCTION, log_format=LogFormat.CONSOLE)

    assert settings.effective_log_format is LogFormat.CONSOLE


def test_invalid_values_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTINGLAB_ENVIRONMENT", "moon")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.environment = Environment.PRODUCTION  # type: ignore[misc]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_cache_dir_defaults_inside_the_data_dir() -> None:
    assert Settings(data_dir=Path("/srv/data")).effective_cache_dir == Path("/srv/data/cache")
    assert Settings(cache_dir=Path("/srv/cache")).effective_cache_dir == Path("/srv/cache")


def test_api_keys_are_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTINGLAB_FRED_API_KEY", "not-a-real-key")

    settings = Settings()

    assert settings.fred_api_key is not None
    assert settings.fred_api_key.get_secret_value() == "not-a-real-key"
    assert "not-a-real-key" not in repr(settings)
    assert settings.alphavantage_api_key is None


@pytest.mark.parametrize(
    ("name", "value"),
    [("HTTP_TIMEOUT_SECONDS", "0"), ("HTTP_MAX_ATTEMPTS", "0"), ("MAX_CONCURRENCY", "1000")],
)
def test_network_settings_are_bounded(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(f"INVESTINGLAB_{name}", value)

    with pytest.raises(ValidationError):
        Settings()


def test_the_documented_env_example_loads_cleanly() -> None:
    example = Path(__file__).parents[5] / ".env.example"
    Path(".env").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    settings = Settings()

    assert settings.log_format is None
    assert settings.cache_dir is None
    assert settings.fred_api_key is None
