"""Request identifiers and access logs."""

from __future__ import annotations

import contextlib
import re
import time
import uuid
from typing import TYPE_CHECKING, Final

import structlog

from investinglab.config import get_logger
from investinglab_api import telemetry

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["REQUEST_ID_HEADER", "RequestContextMiddleware"]

log = get_logger("investinglab_api.access")

REQUEST_ID_HEADER: Final = "X-Request-ID"
_VALID_ID: Final = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    """Give every request an id (or accept a well-formed one) and log its outcome.

    The id is returned in ``X-Request-ID``, bound to every log line of the request and
    quoted in Problem Details (``instance``), so a failure seen in the browser can be found
    in the logs. When the API traces, it is also an attribute of the request's span, and
    nothing a health probe does is traced (ADR-0048). Pure ASGI, so streaming responses are
    not buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve one ASGI connection with a request id bound to it."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value for key, value in scope["headers"]}
        given = headers.get(REQUEST_ID_HEADER.lower(), b"").decode("latin-1")
        request_id = given if _VALID_ID.fullmatch(given) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                message.setdefault("headers", []).append(
                    (REQUEST_ID_HEADER.encode("latin-1"), request_id.encode("latin-1"))
                )
            await send(message)

        telemetry.annotate(**{"investinglab.request_id": request_id})
        probe = scope["path"] in telemetry.PROBE_PATHS
        with (
            structlog.contextvars.bound_contextvars(request_id=request_id),
            telemetry.untraced() if probe else contextlib.nullcontext(),
        ):
            try:
                await self._app(scope, receive, send_with_id)
            finally:
                log.info(
                    "http_request_served",
                    method=scope["method"],
                    path=scope["path"],
                    status=status,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                )
