"""Economic series: rates, macro figures and indices with their publication dates."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from investinglab.ports import VintageMode
from investinglab_api.dependencies import ToolkitDep
from investinglab_api.mappers import economic_series_out
from investinglab_api.routers import problems
from investinglab_api.schemas.economic import EconomicSeriesOut

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["economic"])


@router.get(
    "/economic/series",
    summary="An economic series",
    response_model=EconomicSeriesOut,
    responses=problems(404, 422, 503),
)
async def series(
    toolkit: ToolkitDep,
    series_id: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9._\-]+$",
            description="Provider id: FNG (crypto Fear & Greed), EST.B.EU000A2X2A25.WT (€STR)...",
            examples=["FNG"],
        ),
    ],
    *,
    start: Annotated[date | None, Query(description="First period (inclusive).")] = None,
    end: Annotated[date | None, Query(description="Last period (inclusive).")] = None,
    mode: Annotated[
        VintageMode, Query(description="Vintages: first releases (point-in-time), all, latest.")
    ] = VintageMode.FIRST_RELEASE,
) -> EconomicSeriesOut:
    """Values of an economic series with the day each became public."""
    result = await toolkit.economic(series_id, start=start, end=end, mode=mode)
    return economic_series_out(result)
