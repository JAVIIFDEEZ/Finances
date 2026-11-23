"""Command line and application factory defaults."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from investinglab_api import __main__ as cli
from investinglab_api.app import create_app
from investinglab_api.persistence import migrate
from investinglab_api.settings import get_api_settings

if TYPE_CHECKING:
    from pathlib import Path


def test_the_openapi_document_can_be_written(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    assert cli.main(["--openapi", str(target)]) == 0

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["info"]["title"] == "InvestingLab API"


def test_the_server_runs_the_factory_with_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    monkeypatch.setenv("INVESTINGLAB_API_PORT", "8123")

    assert cli.main(["--reload"]) == 0

    app, options = calls[0]
    assert app == "investinglab_api.app:create_app"
    assert options["factory"] is True
    assert (options["host"], options["port"], options["reload"]) == ("127.0.0.1", 8123, True)
    assert options["access_log"] is False  # the API's own access log has the request id


def test_db_needs_a_database_url(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["db", "current"]) == 2

    assert "INVESTINGLAB_API_DATABASE_URL" in capsys.readouterr().err


def test_a_database_that_does_not_answer_is_named_without_its_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Port 1 of this machine: nothing listens there, the connection is refused at once.
    url = "postgresql+psycopg://someone:not-a-real-password@127.0.0.1:1/investinglab"
    monkeypatch.setenv("INVESTINGLAB_API_DATABASE_URL", url)
    get_api_settings.cache_clear()

    assert cli.main(["db", "upgrade"]) == 1

    error = capsys.readouterr().err
    assert "Could not reach the database at 127.0.0.1:1/investinglab" in error
    assert "uv run just db-up" in error
    assert "not-a-real-password" not in error
    assert "someone" not in error


def test_a_migration_interrupted_with_ctrl_c_ends_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(url: str, revision: str = "head") -> None:
        raise KeyboardInterrupt

    monkeypatch.setenv("INVESTINGLAB_API_DATABASE_URL", "postgresql+psycopg://h/x")
    get_api_settings.cache_clear()
    monkeypatch.setattr(migrate, "upgrade", interrupted)

    assert cli.main(["db", "upgrade"]) == 130  # 128 + SIGINT, as shells report it

    assert "left as it was" in capsys.readouterr().err


def test_migrating_does_not_load_the_core() -> None:
    """``just dev`` migrates before the servers: that step must not wait for pandas or SciPy."""
    probe = (
        "import sys, investinglab_api.persistence.migrate; "
        "print(sorted({'pandas', 'scipy', 'investinglab', 'fastapi'} & set(sys.modules)))"
    )

    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], check=True, capture_output=True, text=True
    )

    assert done.stdout.strip() == "[]"


def test_the_persistence_exports_load_when_used() -> None:
    from investinglab_api import persistence  # noqa: PLC0415

    assert persistence.Database.__name__ == "Database"
    assert {"Database", "SqlAuditLog"} <= set(dir(persistence))
    with pytest.raises(AttributeError, match="no attribute 'Nope'"):
        _ = persistence.Nope


@pytest.mark.integration
def test_db_reports_and_upgrades_the_schema(
    postgres: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INVESTINGLAB_API_DATABASE_URL", postgres["owner"])
    get_api_settings.cache_clear()

    assert cli.main(["db", "current"]) == 0
    assert cli.main(["db", "upgrade"]) == 0  # already there: nothing to do, still fine

    output = capsys.readouterr().out
    head = migrate.head_revision()
    assert output.count(f"Database at revision {head} (this version needs {head})") == 2
    assert "postgres:" not in output  # the URL and its password are never printed


def test_db_revision_drafts_a_migration_from_the_models(monkeypatch: pytest.MonkeyPatch) -> None:
    drafted: list[tuple[str | None, dict[str, Any]]] = []
    monkeypatch.setattr(
        "alembic.command.revision",
        lambda config, **options: drafted.append((config.attributes["url"], options)),
    )
    monkeypatch.setattr(migrate, "current_revision", lambda url: "0001")
    monkeypatch.setenv("INVESTINGLAB_API_DATABASE_URL", "postgresql+psycopg://localhost/x")
    get_api_settings.cache_clear()

    assert cli.main(["db", "revision", "-m", "add ledgers"]) == 0
    with pytest.raises(SystemExit):  # a revision without a message says nothing to a reviewer
        cli.main(["db", "revision"])

    assert drafted == [
        ("postgresql+psycopg://localhost/x", {"message": "add ledgers", "autogenerate": True})
    ]


def test_the_default_app_wires_and_closes_its_own_toolkit() -> None:
    app = create_app()  # offline core settings from the environment (see conftest)

    with TestClient(app) as client:
        health = client.get("/health/ready").json()

    assert health["offline"] is True
    assert health["providers"] == []
