"""Service metadata: health, providers, modules of the master and risk-free rates."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from investinglab.domain.instruments import AssetClass
from investinglab.domain.time import Frequency
from investinglab.modules import RequirementStatus
from investinglab.ports import Dataset
from investinglab_api.schemas.common import ApiModel, Point

__all__ = [
    "HealthOut",
    "ModuleOut",
    "ProviderOut",
    "RateLimitOut",
    "RequirementOut",
    "RiskFreeOut",
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


class RateLimitOut(ApiModel):
    """A quota the provider is called within."""

    max_calls: int
    period_seconds: float


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
