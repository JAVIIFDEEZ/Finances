"""Command line and application factory defaults."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi.testclient import TestClient

from investinglab_api import __main__ as cli
from investinglab_api.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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


def test_the_default_app_wires_and_closes_its_own_toolkit() -> None:
    app = create_app()  # offline core settings from the environment (see conftest)

    with TestClient(app) as client:
        health = client.get("/health/ready").json()

    assert health["offline"] is True
    assert health["providers"] == []
