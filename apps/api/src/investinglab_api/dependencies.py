"""Shared request dependencies: the toolkit, the settings and the service limits."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from investinglab.domain.errors import DomainError
from investinglab.toolkit import AsyncToolkit
from investinglab_api.settings import ApiSettings

if TYPE_CHECKING:
    from collections.abc import Sized

__all__ = ["SettingsDep", "ToolkitDep", "at_most", "get_settings", "get_toolkit"]


def get_toolkit(request: Request) -> AsyncToolkit:
    """The toolkit wired at start-up (see :func:`investinglab_api.app.create_app`)."""
    toolkit: AsyncToolkit = request.app.state.toolkit
    return toolkit


def get_settings(request: Request) -> ApiSettings:
    """The settings the application was created with."""
    settings: ApiSettings = request.app.state.settings
    return settings


ToolkitDep = Annotated[AsyncToolkit, Depends(get_toolkit)]
SettingsDep = Annotated[ApiSettings, Depends(get_settings)]


def at_most(items: Sized | int, limit: int, what: str) -> None:
    """Reject a request above one of the service limits.

    Raises:
        DomainError: Answered as an ``invalid-request`` problem.
    """
    count = items if isinstance(items, int) else len(items)
    if count > limit:
        raise DomainError(f"At most {limit} {what} per request, got {count}")
