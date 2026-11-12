"""Saved portfolios: what each owner keeps between sessions."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from investinglab_api import use_cases
from investinglab_api.dependencies import (
    ExpectedVersion,
    OwnerDep,
    PortfoliosDep,
    SettingsDep,
    at_most,
)
from investinglab_api.mappers import portfolio_spec, saved_portfolio_out, saved_portfolio_page
from investinglab_api.routers import problems
from investinglab_api.schemas.portfolio import PortfolioIn, SavedPortfolioOut, SavedPortfolioPage

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/portfolios", tags=["portfolios"])

NO_DATABASE = "The API runs without a database, or the database is not answering."
NOT_FOUND = "The owner has no such portfolio."


def _etag(response: Response, saved: SavedPortfolioOut) -> None:
    response.headers["ETag"] = f'"{saved.version}"'


def _accept(body: PortfolioIn, settings: SettingsDep) -> None:
    at_most(body.holdings, settings.max_symbols, "holdings")
    use_cases.accept_weights(body)


@router.get(
    "",
    summary="List saved portfolios",
    response_model=SavedPortfolioPage,
    responses=problems(422, s503=NO_DATABASE),
)
async def list_saved(
    owner: OwnerDep,
    portfolios: PortfoliosDep,
    limit: Annotated[int, Query(ge=1, le=200, description="Most portfolios in a page.")] = 50,
    cursor: Annotated[str | None, Query(description="`next_cursor` of the page before.")] = None,
) -> SavedPortfolioPage:
    """The owner's portfolios, most recently updated first."""
    page = await portfolios.list(owner.owner_id, limit=limit, cursor=cursor)
    return saved_portfolio_page(page)


@router.post(
    "",
    summary="Save a portfolio",
    status_code=201,
    response_model=SavedPortfolioOut,
    responses=problems(409, 422, s503=NO_DATABASE),
)
async def save(  # noqa: PLR0917 - FastAPI injects them by name
    body: PortfolioIn,
    request: Request,
    response: Response,
    owner: OwnerDep,
    portfolios: PortfoliosDep,
    settings: SettingsDep,
) -> SavedPortfolioOut:
    """Save a portfolio under its name; the `ETag` is the version later changes must quote."""
    _accept(body, settings)
    saved = saved_portfolio_out(await portfolios.add(owner.owner_id, portfolio_spec(body)))
    response.headers["Location"] = str(request.url_for("read_saved", portfolio_id=saved.id))
    _etag(response, saved)
    return saved


@router.get(
    "/{portfolio_id}",
    name="read_saved",
    summary="Read a saved portfolio",
    response_model=SavedPortfolioOut,
    responses=problems(422, s404=NOT_FOUND, s503=NO_DATABASE),
)
async def read_saved(
    portfolio_id: UUID, response: Response, owner: OwnerDep, portfolios: PortfoliosDep
) -> SavedPortfolioOut:
    """One saved portfolio and its current version (`ETag`)."""
    saved = saved_portfolio_out(await portfolios.get(owner.owner_id, portfolio_id))
    _etag(response, saved)
    return saved


@router.put(
    "/{portfolio_id}",
    summary="Replace a saved portfolio",
    response_model=SavedPortfolioOut,
    responses=problems(409, 412, 422, 428, s404=NOT_FOUND, s503=NO_DATABASE),
)
async def replace(  # noqa: PLR0917 - FastAPI injects them by name
    portfolio_id: UUID,
    body: PortfolioIn,
    response: Response,
    owner: OwnerDep,
    portfolios: PortfoliosDep,
    settings: SettingsDep,
    version: ExpectedVersion,
) -> SavedPortfolioOut:
    """Replace the portfolio read at the version in `If-Match`; nothing is lost if it changed."""
    _accept(body, settings)
    record = await portfolios.replace(
        owner.owner_id, portfolio_id, portfolio_spec(body), expected_version=version
    )
    saved = saved_portfolio_out(record)
    _etag(response, saved)
    return saved


@router.delete(
    "/{portfolio_id}",
    summary="Delete a saved portfolio",
    status_code=204,
    responses=problems(412, 422, 428, s404=NOT_FOUND, s503=NO_DATABASE),
)
async def delete(
    portfolio_id: UUID, owner: OwnerDep, portfolios: PortfoliosDep, version: ExpectedVersion
) -> None:
    """Delete the portfolio read at the version in `If-Match`."""
    await portfolios.remove(owner.owner_id, portfolio_id, expected_version=version)
