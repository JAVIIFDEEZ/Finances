"""Backtests: a strategy on one symbol with its market's costs, and what they can be told.

``POST /api/v1/backtests`` answers within the request; ``POST /api/v1/jobs/backtests`` runs
the same in the background, for what may take longer (years of intraday bars).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from investinglab.analytics.search import CLASSICS
from investinglab.domain.costs import COST_PROFILES
from investinglab_api import use_cases
from investinglab_api.dependencies import ToolkitDep
from investinglab_api.mappers import backtest_out, classic_out, cost_profile_out
from investinglab_api.routers import problems
from investinglab_api.schemas.backtest import BacktestIn, BacktestOut, ClassicOut, CostProfileOut

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["backtests"])


@router.post(
    "/backtests",
    summary="Backtest a strategy",
    response_model=BacktestOut,
    responses=problems(404, 422, 503, 504),
)
async def backtests(body: BacktestIn, toolkit: ToolkitDep) -> BacktestOut:
    """Trade a strategy on one symbol with the costs of its market (ADR-0050, ADR-0051).

    A year of history before `start` warms its indicators up; it trades from `start`. The
    costs are the profile's (where the symbol trades by default): its commission, the tax
    of each day's purchases, the borrow of a short and, for a perpetual, the funding its
    venue published.
    """
    result = await use_cases.backtest(toolkit, body)
    return await asyncio.to_thread(backtest_out, result)


@router.get(
    "/strategies/classics",
    summary="List the classic strategies",
    response_model=list[ClassicOut],
)
async def list_classics() -> list[ClassicOut]:
    """The classic strategies written in the grammar (CryptoWorld's seeds), by name."""
    return [classic_out(name, spec) for name, spec in CLASSICS.items()]


@router.get(
    "/cost-profiles",
    summary="List the markets' cost profiles",
    response_model=list[CostProfileOut],
)
async def list_cost_profiles() -> list[CostProfileOut]:
    """Each market's costs (ADR-0051).

    Published fees with their sources and date, the assumptions said as such, and what a
    backtest leaves out.
    """
    return [cost_profile_out(profile) for profile in COST_PROFILES.values()]
