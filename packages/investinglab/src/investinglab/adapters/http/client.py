"""Resilient asynchronous HTTP client shared by every provider adapter (ADR-0012).

* **Retries** with exponential backoff and jitter for transient failures (timeouts,
  connection errors, 5xx, 429), honouring ``Retry-After`` when the provider sends it.
* **Rate limiting** per provider: every configured quota is respected before each call.
* **Error translation** to the port's :mod:`investinglab.ports.errors` types.
* **Secret hygiene**: credentials in query parameters are redacted from logs and errors.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from investinglab import __version__
from investinglab.config.logging import get_logger
from investinglab.ports.errors import (
    AuthenticationError,
    ProviderDataError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from types import TracebackType

    from investinglab.ports.market_data import RateLimit

__all__ = ["HttpClient", "RetryPolicy", "redact"]

log = get_logger(__name__)

SECRET_PARAMETERS: Final = frozenset(
    {"api_key", "apikey", "key", "token", "access_token", "secret", "password"}
)
USER_AGENT: Final = f"InvestingLab/{__version__} (+https://github.com/JAVIIFDEEZ/Finances)"

type QueryValue = str | int | float | bool | None
type QueryParams = Mapping[str, QueryValue]


def redact(params: QueryParams | None) -> dict[str, QueryValue]:
    """Copy of ``params`` with credential values replaced by ``***``."""
    return {
        name: ("***" if name.lower() in SECRET_PARAMETERS else value)
        for name, value in (params or {}).items()
    }


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How transient failures are retried.

    Attributes:
        max_attempts: Total attempts, including the first one.
        initial_backoff: First backoff in seconds (doubles after each attempt, with jitter).
        max_backoff: Upper bound of any single wait, including ``Retry-After`` values.
    """

    max_attempts: int = 4
    initial_backoff: float = 0.5
    max_backoff: float = 30.0


class HttpClient:
    """GET-only JSON/text client for data providers.

    Args:
        provider: Provider slug, used in errors and logs.
        base_url: Root URL of the provider API.
        timeout: Seconds before a request times out.
        retry: Retry policy for transient failures.
        rate_limits: Quotas to respect; every one of them applies to each call.
        headers: Extra headers (the User-Agent identifies InvestingLab by default).
        transport: Optional httpx transport (tests, proxies).
        sleep: Coroutine used to wait between retries (injectable for tests).
    """

    def __init__(
        self,
        provider: str,
        *,
        base_url: str,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        rate_limits: Sequence[RateLimit] = (),
        headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._provider = provider
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._limiters = [AsyncLimiter(r.max_calls, r.period_seconds) for r in rate_limits]
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            transport=transport,
            follow_redirects=True,
        )

    @property
    def provider(self) -> str:
        """Provider slug."""
        return self._provider

    async def get_json(self, path: str, params: QueryParams | None = None) -> Any:  # noqa: ANN401
        """GET ``path`` and decode the JSON body.

        Raises:
            ProviderError: Translated failure (see the module docstring).
        """
        response = await self._get(path, params)
        try:
            return response.json()
        except ValueError as error:
            raise ProviderDataError(self._provider, f"invalid JSON from {path}") from error

    async def get_text(self, path: str, params: QueryParams | None = None) -> str:
        """GET ``path`` and return the body as text (CSV, XML...)."""
        return (await self._get(path, params)).text

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ── Internals ────────────────────────────────────────────────────

    async def _get(self, path: str, params: QueryParams | None) -> httpx.Response:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry.max_attempts),
            wait=self._wait,
            retry=retry_if_exception(lambda e: isinstance(e, ProviderError) and e.retryable),
            sleep=self._sleep,
            before_sleep=self._log_retry,
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._send(path, params)
        raise AssertionError("unreachable")  # pragma: no cover - reraise=True always raises

    async def _send(self, path: str, params: QueryParams | None) -> httpx.Response:
        for limiter in self._limiters:
            await limiter.acquire()
        query = {k: v for k, v in (params or {}).items() if v is not None}
        started = time.perf_counter()
        try:
            response = await self._client.get(path, params=query)
        except httpx.TimeoutException as error:
            raise ProviderUnavailableError(self._provider, f"timeout on {path}") from error
        except httpx.TransportError as error:
            raise ProviderUnavailableError(
                self._provider, f"connection error on {path}: {type(error).__name__}"
            ) from error
        log.debug(
            "http_request",
            provider=self._provider,
            path=path,
            params=redact(query),
            status=response.status_code,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        self._raise_for_status(response, path)
        return response

    def _raise_for_status(self, response: httpx.Response, path: str) -> None:
        status = response.status_code
        if status < 400:  # noqa: PLR2004
            return
        where = f"HTTP {status} on {path}"
        if status in {401, 403}:
            raise AuthenticationError(self._provider, f"{where}: check the API credentials")
        if status == 404:  # noqa: PLR2004
            raise SymbolNotFoundError(self._provider, f"{where}: resource not found")
        if status == 429:  # noqa: PLR2004
            raise RateLimitedError(self._provider, where, _retry_after(response))
        if status == 408 or status >= 500:  # noqa: PLR2004
            raise ProviderUnavailableError(self._provider, where)
        raise UnsupportedRequestError(self._provider, where)

    def _wait(self, state: RetryCallState) -> float:
        error = state.outcome.exception() if state.outcome else None
        if isinstance(error, RateLimitedError) and error.retry_after is not None:
            return min(error.retry_after, self._retry.max_backoff)
        backoff = wait_exponential_jitter(
            multiplier=self._retry.initial_backoff,
            max=self._retry.max_backoff,
            jitter=self._retry.initial_backoff,
        )
        return float(backoff(state))

    def _log_retry(self, state: RetryCallState) -> None:
        error = state.outcome.exception() if state.outcome else None
        log.warning(
            "http_retry",
            provider=self._provider,
            attempt=state.attempt_number,
            error=type(error).__name__,
            detail=str(error),
        )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form: fall back to exponential backoff
