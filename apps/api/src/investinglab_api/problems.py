"""Errors as RFC 9457 Problem Details (``application/problem+json``).

Every failure the API reports has a stable ``type`` URI pointing at its documentation, a
short ``title``, the HTTP ``status``, a human ``detail`` and the request id (``instance``),
plus machine-readable extensions where useful (``errors``, ``attempts``). Internal details
(tracebacks, provider URLs) never reach the client.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, cast

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from investinglab.config import get_logger
from investinglab.domain.errors import DomainError
from investinglab.ports import (
    DuplicateNameError,
    RecordNotFoundError,
    RepositoryUnavailableError,
    VersionConflictError,
)
from investinglab.services import DataUnavailableError
from investinglab_api.dependencies import PersistenceNotConfiguredError, PreconditionRequiredError
from investinglab_api.middleware import REQUEST_ID_HEADER

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

__all__ = ["PROBLEM_JSON", "ProblemType", "install_problem_handlers", "problem"]

log = get_logger(__name__)

PROBLEM_JSON: Final = "application/problem+json"
DOCS: Final = "https://github.com/JAVIIFDEEZ/Finances/blob/development/docs/guide/api.md"


class ProblemType(StrEnum):
    """Kinds of problem, each documented in the API guide."""

    INVALID_REQUEST = "invalid-request"
    NOT_FOUND = "not-found"
    DATA_NOT_FOUND = "data-not-found"
    DATA_UNAVAILABLE = "data-unavailable"
    TIMEOUT = "timeout"
    NAME_CONFLICT = "name-conflict"
    VERSION_CONFLICT = "version-conflict"
    PRECONDITION_REQUIRED = "precondition-required"
    PERSISTENCE_NOT_CONFIGURED = "persistence-not-configured"
    PERSISTENCE_UNAVAILABLE = "persistence-unavailable"
    HTTP_ERROR = "http-error"
    INTERNAL_ERROR = "internal-error"

    @property
    def uri(self) -> str:
        """Documentation URI of the problem type."""
        return f"{DOCS}#{self.value}"


def problem(
    request: Request,
    status: int,
    kind: ProblemType,
    title: str,
    detail: str,
    **extensions: Any,  # noqa: ANN401 - RFC 9457 extension members are free-form
) -> JSONResponse:
    """A Problem Details response for ``request``."""
    body = {
        "type": kind.uri,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": f"urn:request:{getattr(request.state, 'request_id', 'unknown')}",
        **extensions,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


async def _validation(request: Request, exc: Exception) -> JSONResponse:
    error = cast("RequestValidationError", exc)
    errors = [
        {
            "location": [str(part) for part in item.get("loc", ())],
            "message": str(item.get("msg", "")),
            "type": str(item.get("type", "")),
        }
        for item in error.errors()
    ]
    return problem(
        request,
        422,
        ProblemType.INVALID_REQUEST,
        "Invalid request",
        "The request does not match the documented schema.",
        errors=errors,
    )


async def _domain(request: Request, error: Exception) -> JSONResponse:
    problems = getattr(error, "problems", None)
    errors = [{"message": item} for item in problems] if problems else []
    return problem(
        request, 422, ProblemType.INVALID_REQUEST, "Invalid request", str(error), errors=errors
    )


async def _unavailable(request: Request, exc: Exception) -> JSONResponse:
    error = cast("DataUnavailableError", exc)
    attempts = [
        {"provider": a.provider, "error": a.error_type, "message": a.message}
        for a in error.attempts
    ]
    not_found = bool(error.attempts) and all(
        a.error_type == "SymbolNotFoundError" for a in error.attempts
    )
    if not_found or not error.attempts:
        return problem(
            request,
            404,
            ProblemType.DATA_NOT_FOUND,
            "Data not found",
            str(error),
            attempts=attempts,
        )
    retryable = any(a.retryable for a in error.attempts)
    response = problem(
        request,
        503,
        ProblemType.DATA_UNAVAILABLE,
        "Data source unavailable",
        str(error),
        attempts=attempts,
    )
    if retryable:
        response.headers["Retry-After"] = "30"
    return response


async def _timeout(request: Request, error: Exception) -> JSONResponse:
    return problem(
        request,
        504,
        ProblemType.TIMEOUT,
        "Timed out",
        f"The request took too long: {str(error) or 'no detail'}",
    )


async def _record_not_found(request: Request, error: Exception) -> JSONResponse:
    return problem(request, 404, ProblemType.NOT_FOUND, "Not found", str(error))


async def _name_conflict(request: Request, error: Exception) -> JSONResponse:
    return problem(request, 409, ProblemType.NAME_CONFLICT, "Name already in use", str(error))


async def _version_conflict(request: Request, exc: Exception) -> JSONResponse:
    error = cast("VersionConflictError", exc)
    response = problem(
        request,
        412,
        ProblemType.VERSION_CONFLICT,
        "Changed since it was read",
        "The record changed since the version in If-Match: read it again and retry.",
        current_version=error.current_version,
    )
    response.headers["ETag"] = f'"{error.current_version}"'
    return response


async def _precondition_required(request: Request, _: Exception) -> JSONResponse:
    return problem(
        request,
        428,
        ProblemType.PRECONDITION_REQUIRED,
        "Version required",
        "Send the ETag last read in an If-Match header: a change applies to a known version.",
    )


async def _persistence_not_configured(request: Request, _: Exception) -> JSONResponse:
    return problem(
        request,
        503,
        ProblemType.PERSISTENCE_NOT_CONFIGURED,
        "No database configured",
        "This endpoint stores data and the API runs without a database "
        "(INVESTINGLAB_API_DATABASE_URL).",
    )


async def _persistence_unavailable(request: Request, _: Exception) -> JSONResponse:
    response = problem(
        request,
        503,
        ProblemType.PERSISTENCE_UNAVAILABLE,
        "Database unavailable",
        "The database is not answering; retry later.",
    )
    response.headers["Retry-After"] = "10"
    return response


async def _http(request: Request, exc: Exception) -> JSONResponse:
    error = cast("StarletteHTTPException", exc)
    kind = ProblemType.NOT_FOUND if error.status_code == 404 else ProblemType.HTTP_ERROR  # noqa: PLR2004
    response = problem(request, error.status_code, kind, str(error.detail), str(error.detail))
    for name, value in (error.headers or {}).items():
        response.headers[name] = value
    return response


async def _unexpected(request: Request, error: Exception) -> JSONResponse:
    log.error(
        "unhandled_error",
        request_id=getattr(request.state, "request_id", None),
        error=type(error).__name__,
        exc_info=error,
    )
    response = problem(
        request,
        500,
        ProblemType.INTERNAL_ERROR,
        "Internal error",
        "The server could not complete the request; quote the instance id when reporting it.",
    )
    # Starlette answers unhandled errors outside the other middleware: add the id here.
    response.headers[REQUEST_ID_HEADER] = getattr(request.state, "request_id", "unknown")
    return response


def install_problem_handlers(app: FastAPI) -> None:
    """Translate every error into a Problem Details response."""
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(DataUnavailableError, _unavailable)
    app.add_exception_handler(DomainError, _domain)
    app.add_exception_handler(TimeoutError, _timeout)
    app.add_exception_handler(RecordNotFoundError, _record_not_found)
    app.add_exception_handler(DuplicateNameError, _name_conflict)
    app.add_exception_handler(VersionConflictError, _version_conflict)
    app.add_exception_handler(PreconditionRequiredError, _precondition_required)
    app.add_exception_handler(PersistenceNotConfiguredError, _persistence_not_configured)
    app.add_exception_handler(RepositoryUnavailableError, _persistence_unavailable)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(Exception, _unexpected)
