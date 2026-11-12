"""Command line and application factory defaults."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from investinglab_api import __main__ as cli
from investinglab_api.app import create_app
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


@pytest.mark.integration
def test_db_reports_and_upgrades_the_schema(
    postgres: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INVESTINGLAB_API_DATABASE_URL", postgres["owner"])
    get_api_settings.cache_clear()

    assert cli.main(["db", "current"]) == 0
    assert cli.main(["db", "upgrade"]) == 0  # already there: nothing to do, still fine

    output = capsys.readouterr().out
    assert output.count("Database at revision 0001 (this version needs 0001)") == 2
    assert "postgres:" not in output  # the URL and its password are never printed


def test_the_default_app_wires_and_closes_its_own_toolkit() -> None:
    app = create_app()  # offline core settings from the environment (see conftest)

    with TestClient(app) as client:
        health = client.get("/health/ready").json()

    assert health["offline"] is True
    assert health["providers"] == []
