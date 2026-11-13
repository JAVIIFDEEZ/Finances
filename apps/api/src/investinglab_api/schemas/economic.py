"""Economic series: rates, macro figures and indices, with their publication dates."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from investinglab.domain.time import Frequency
from investinglab_api.schemas.common import ApiModel
from investinglab_api.schemas.market import SourceOut

__all__ = ["EconomicObservationOut", "EconomicSeriesOut"]


class EconomicObservationOut(ApiModel):
    """One published value of an observation."""

    time: date = Field(description="Period measured.")
    published_at: date = Field(description="Day the value became public (point-in-time).")
    value: float


class EconomicSeriesOut(ApiModel):
    """An economic series with every vintage the request asked for (ADR-0009)."""

    series_id: str
    title: str
    units: str
    frequency: Frequency
    source: SourceOut
    has_revisions: bool = Field(description="Whether any observation has several vintages.")
    observations: list[EconomicObservationOut] = Field(
        description="Sorted by period and publication date."
    )
