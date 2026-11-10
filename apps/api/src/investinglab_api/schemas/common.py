"""Building blocks shared by every schema."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investinglab.domain.time import Frequency

__all__ = [
    "ApiModel",
    "DateRange",
    "FiniteFloat",
    "Matrix",
    "Point",
    "Problem",
    "ProblemError",
    "RequestModel",
    "finite",
]

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
"""A float that must be finite (NaN and infinity are refused in requests)."""


def finite(value: float | None) -> float | None:
    """``None`` for NaN or infinite values: JSON has no NaN, and an undefined figure is null."""
    if value is None or not math.isfinite(value):
        return None
    return float(value)


class ApiModel(BaseModel):
    """Base of every response: immutable, documented field by field."""

    model_config = ConfigDict(frozen=True)


class RequestModel(BaseModel):
    """Base of every request body: unknown fields are an error, not silently ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DateRange(RequestModel):
    """Optional history bounds (session dates, both inclusive)."""

    start: date | None = Field(default=None, description="First session (inclusive).")
    end: date | None = Field(default=None, description="Last session (inclusive).")
    frequency: Frequency = Field(default=Frequency.DAY_1, description="Bar frequency.")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start and self.end and self.start > self.end:
            msg = f"start {self.start} is after end {self.end}"
            raise ValueError(msg)
        return self


class Point(ApiModel):
    """A value at a date or instant (``null`` when undefined)."""

    time: date | datetime
    value: float | None


class Matrix(ApiModel):
    """A square matrix with labelled rows and columns (``null`` where undefined)."""

    labels: list[str]
    values: list[list[float | None]]


class ProblemError(ApiModel):
    """One problem behind an ``invalid-request`` response."""

    message: str
    location: list[str] | None = None
    type: str | None = None


class Problem(ApiModel):
    """RFC 9457 Problem Details: how every error is reported."""

    type: str = Field(description="Documentation URI of the kind of problem.")
    title: str = Field(description="Short, stable summary of the kind of problem.")
    status: int = Field(description="HTTP status code.")
    detail: str = Field(description="Explanation of this occurrence.")
    instance: str = Field(description="Request identifier (``urn:request:<id>``).")
    errors: list[ProblemError] | None = Field(
        default=None, description="Individual problems of an invalid request."
    )
    attempts: list[dict[str, str]] | None = Field(
        default=None, description="Providers tried for unavailable data, with their errors."
    )
