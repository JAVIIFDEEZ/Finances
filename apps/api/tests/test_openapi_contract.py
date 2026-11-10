"""The committed OpenAPI document is the contract the web client is generated from."""

from __future__ import annotations

import json
from pathlib import Path

from investinglab_api.app import create_app

CONTRACT = Path(__file__).resolve().parents[1] / "openapi.json"


def test_the_committed_contract_matches_the_api() -> None:
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert committed == create_app().openapi(), (
        "apps/api/openapi.json is stale: run `uv run just openapi` and commit it"
    )
