"""Shared pytest configuration for the core library."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from investinglab.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _isolated_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Keep tests hermetic: ignore the developer's .env and INVESTINGLAB_* variables."""
    for key in list(os.environ):
        if key.startswith("INVESTINGLAB_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
