"""What a repository takes and returns: portfolio definitions and cursors."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from investinglab.domain.errors import DomainError
from investinglab.ports import (
    PortfolioRepository,
    PortfolioSpec,
    VersionConflictError,
    decode_cursor,
    encode_cursor,
)
from support.repositories import InMemoryPortfolioRepository

WEIGHTS = (("AAA.MC", 0.6), ("BBB.MC", 0.4))


def test_a_definition_keeps_the_owners_order_and_trims_the_name() -> None:
    spec = PortfolioSpec(name="  Core  ", weights=WEIGHTS)

    assert spec.name == "Core"
    assert [symbol for symbol, _ in spec.weights] == ["AAA.MC", "BBB.MC"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "   "}, "1 to 80 characters"),
        ({"name": "x" * 81}, "1 to 80 characters"),
        ({"weights": ()}, "at least one holding"),
        ({"weights": (("AAA.MC", 0.5), ("AAA.MC", 0.5))}, "distinct"),
        ({"weights": (("", 1.0),)}, "non-empty symbols"),
        ({"weights": (("AAA.MC", float("nan")),)}, "finite"),
        ({"start": date(2025, 1, 2), "end": date(2025, 1, 1)}, "after end"),
    ],
    ids=["blank", "long", "empty", "duplicated", "no-symbol", "nan", "dates"],
)
def test_inconsistent_definitions_are_refused(changes: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {"name": "Core", "weights": WEIGHTS, **changes}

    with pytest.raises(DomainError, match=message):
        PortfolioSpec(**fields)  # type: ignore[arg-type]


def test_a_cursor_round_trips_and_is_opaque() -> None:
    moment = datetime(2026, 11, 12, 9, 30, 15, 123456, tzinfo=UTC)
    record = UUID("5e0c2d8e-7a52-4d6b-9d0c-3f1f6c5a9b11")

    cursor = encode_cursor(moment, record)

    assert decode_cursor(cursor) == (moment, record)
    assert "2026" not in cursor


@pytest.mark.parametrize("cursor", ["", "nonsense", "bm8tcGlwZQ", "MjAyNi0xMS0xMlQwOTozMDowMHx4"])
def test_a_foreign_cursor_is_refused(cursor: str) -> None:
    with pytest.raises(DomainError, match="cursor"):
        decode_cursor(cursor)


def test_a_cursor_without_timezone_is_refused() -> None:
    forged = base64.urlsafe_b64encode(f"2026-01-01T00:00:00|{UUID(int=1)}".encode()).decode()

    with pytest.raises(DomainError, match="cursor"):
        decode_cursor(forged)


def test_a_version_conflict_says_where_the_record_is_now() -> None:
    error = VersionConflictError(4)

    assert error.current_version == 4
    assert "version 4" in str(error)


def test_the_in_memory_repository_is_a_portfolio_repository() -> None:
    assert isinstance(InMemoryPortfolioRepository(), PortfolioRepository)
