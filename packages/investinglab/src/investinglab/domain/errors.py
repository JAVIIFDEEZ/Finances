"""Domain error hierarchy.

Validation errors collect *every* problem found instead of stopping at the first one, so a
caller fixing an input sees the full list at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "DomainError",
    "IncompatibleSeriesError",
    "InvalidIdentifierError",
    "InvalidPortfolioError",
    "InvalidSeriesError",
    "InvestingLabError",
    "UnknownCurrencyError",
]


class InvestingLabError(Exception):
    """Base class of every error raised by InvestingLab."""


class DomainError(InvestingLabError, ValueError):
    """A domain invariant was violated by the provided values."""


class _ProblemsError(DomainError):
    """Domain error that reports a list of problems about a named subject."""

    kind: str = "value"

    def __init__(self, subject: str, problems: Sequence[str]) -> None:
        self.subject = subject
        self.problems: tuple[str, ...] = tuple(problems)
        detail = "; ".join(self.problems) if self.problems else "unspecified problem"
        super().__init__(f"Invalid {self.kind} {subject!r}: {detail}")


class InvalidSeriesError(_ProblemsError):
    """A time series does not satisfy the structural invariants of its type."""

    kind = "series"


class InvalidPortfolioError(_ProblemsError):
    """A portfolio definition is inconsistent (weights, currencies, frequencies...)."""

    kind = "portfolio"


class IncompatibleSeriesError(_ProblemsError):
    """Several series cannot be combined (different frequencies, duplicated symbols...)."""

    kind = "combination"


class InvalidIdentifierError(DomainError):
    """A security identifier (ISIN, FIGI, CIK, LEI) is malformed or fails its checksum."""


class UnknownCurrencyError(DomainError):
    """A currency code is not a known ISO 4217 or supported digital-asset code."""
