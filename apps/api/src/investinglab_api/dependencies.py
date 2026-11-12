"""Shared request dependencies: the toolkit, the settings, the owner and the repositories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, Request

from investinglab.domain.errors import DomainError
from investinglab.ports import PortfolioRepository
from investinglab.toolkit import AsyncToolkit
from investinglab_api.settings import ApiSettings

if TYPE_CHECKING:
    from collections.abc import Sized

__all__ = [
    "ExpectedVersion",
    "OwnerDep",
    "PersistenceNotConfiguredError",
    "PortfoliosDep",
    "PreconditionRequiredError",
    "Principal",
    "SettingsDep",
    "ToolkitDep",
    "at_most",
    "get_portfolios",
    "get_principal",
    "get_settings",
    "get_toolkit",
]


class PersistenceNotConfiguredError(Exception):
    """The endpoint stores state and the API runs without a database."""


class PreconditionRequiredError(Exception):
    """A write came without the version of the record it means to change."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a request acts for.

    Attributes:
        owner_id: Owner of everything the request reads and writes.
    """

    owner_id: str


def get_toolkit(request: Request) -> AsyncToolkit:
    """The toolkit wired at start-up (see :func:`investinglab_api.app.create_app`)."""
    toolkit: AsyncToolkit = request.app.state.toolkit
    return toolkit


def get_settings(request: Request) -> ApiSettings:
    """The settings the application was created with."""
    settings: ApiSettings = request.app.state.settings
    return settings


def get_principal(request: Request) -> Principal:
    """The owner the request acts for.

    Until authentication arrives (F7) that is the single local owner of the settings: the
    API must only listen on this machine.
    """
    settings: ApiSettings = request.app.state.settings
    return Principal(settings.local_owner)


def get_portfolios(request: Request) -> PortfolioRepository:
    """The repository of saved portfolios.

    Raises:
        PersistenceNotConfiguredError: The API runs without a database.
    """
    repository: PortfolioRepository | None = request.app.state.portfolios
    if repository is None:
        raise PersistenceNotConfiguredError
    return repository


_ETAG = re.compile(r'"(\d{1,9})"')


def expected_version(
    if_match: Annotated[
        str | None,
        Header(description='Version the change applies to: the `ETag` last read (`"3"`).'),
    ] = None,
) -> int:
    """The version a write expects the record to be at (its ``If-Match`` header).

    Raises:
        PreconditionRequiredError: The header is missing.
        DomainError: The header is not an ``ETag`` of this API.
    """
    if if_match is None:
        raise PreconditionRequiredError
    match = _ETAG.fullmatch(if_match.strip())
    if match is None:
        raise DomainError(f'If-Match takes the ETag last read (like "3"), not {if_match!r}')
    return int(match.group(1))


ToolkitDep = Annotated[AsyncToolkit, Depends(get_toolkit)]
SettingsDep = Annotated[ApiSettings, Depends(get_settings)]
OwnerDep = Annotated[Principal, Depends(get_principal)]
PortfoliosDep = Annotated[PortfolioRepository, Depends(get_portfolios)]
ExpectedVersion = Annotated[int, Depends(expected_version)]


def at_most(items: Sized | int, limit: int, what: str) -> None:
    """Reject a request above one of the service limits.

    Raises:
        DomainError: Answered as an ``invalid-request`` problem.
    """
    count = items if isinstance(items, int) else len(items)
    if count > limit:
        raise DomainError(f"At most {limit} {what} per request, got {count}")
