"""Service metadata: health, providers, modules of the master and risk-free rates."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from investinglab.domain.instruments import AssetClass
from investinglab.domain.rate_series import RateKind
from investinglab.domain.time import Frequency
from investinglab.modules import RequirementStatus
from investinglab.ports import Dataset
from investinglab_api.schemas.common import ApiModel, Point

__all__ = [
    "CanaryOut",
    "HealthOut",
    "ModuleOut",
    "ProviderOut",
    "RateLimitOut",
    "RequirementOut",
    "RiskFreeOut",
    "SourceStatusOut",
]


class HealthOut(ApiModel):
    """Liveness or readiness of the service."""

    status: Literal["ok"]
    version: str
    core_version: str
    providers: list[str] = Field(description="Registered providers, in order of preference.")
    offline: bool = Field(description="Whether remote providers are disabled.")
    database: Literal["not_configured", "ok", "migrations_pending", "unavailable"] = Field(
        default="not_configured",
        description="State of the database behind the endpoints that store data.",
    )
    workers: int | None = Field(
        default=None,
        description=(
            "Workers taking background jobs now (a recent heartbeat); null without a database "
            "or on the liveness probe."
        ),
    )


class SourceStatusOut(ApiModel):
    """Whether a data source answers its canary, and how fresh its data is (ADR-0047)."""

    provider: str
    checked_at: datetime = Field(description="When it was last checked.")
    ok: bool = Field(description="Whether it answered that check with data.")
    latency_seconds: float = Field(description="Seconds it took to answer (or to fail).")
    latest_at: datetime | None = Field(
        description="Instant of the latest observation it answered (a daily bar: its date)."
    )
    error: str | None = Field(description="What went wrong, when it failed.")
    last_ok_at: datetime | None = Field(description="When it last answered; null if never.")
    failures: int = Field(description="Checks failed in a row (0 when it answered).")


class RateLimitOut(ApiModel):
    """A quota the provider is called within."""

    max_calls: int
    period_seconds: float


class CanaryOut(ApiModel):
    """The small request that checks a source answers (ADR-0047)."""

    dataset: Dataset
    symbol: str = Field(description="What it asks for: a symbol, a series or an asset class.")


class ProviderOut(ApiModel):
    """What a registered provider can serve."""

    name: str
    datasets: list[Dataset]
    asset_classes: list[AssetClass]
    frequencies: list[Frequency]
    requires_api_key: bool
    max_history_days: dict[str, int] = Field(description="Look-back limit by frequency.")
    rate_limits: list[RateLimitOut]
    identifiers: str | None = Field(description="Pattern of the identifiers it serves.")
    rate_kinds: list[RateKind] = Field(description="Holding rates it serves, if any.")
    canary: CanaryOut | None = Field(
        default=None, description="How the worker checks it; null for a source never checked."
    )


class RequirementOut(ApiModel):
    """A requirement of a module and where it is implemented and tested."""

    id: str
    title: str
    status: RequirementStatus
    code: list[str]
    tests: list[str]
    note: str


class ModuleOut(ApiModel):
    """A module of the platform (a block of the master)."""

    slug: str
    block: str
    title: str
    summary: str
    complete: bool
    requirements: list[RequirementOut]


class RiskFreeOut(ApiModel):
    """Effective annual risk-free rate known at each business day."""

    currency: str
    rates: list[Point] = Field(description="Decimal rates; null before any publication.")
