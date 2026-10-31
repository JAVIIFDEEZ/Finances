"""Errors raised by data providers.

Adapters translate every provider-specific failure (HTTP status, malformed payload, missing
symbol...) into one of these types, so the services can decide uniformly whether to retry,
fall back to another provider or report the failure.
"""

from __future__ import annotations

from investinglab.domain.errors import InvestingLabError

__all__ = [
    "AuthenticationError",
    "ProviderDataError",
    "ProviderError",
    "ProviderUnavailableError",
    "RateLimitedError",
    "SymbolNotFoundError",
    "UnsupportedRequestError",
]


class ProviderError(InvestingLabError):
    """A data provider could not serve a request.

    Attributes:
        provider: Provider slug.
        retryable: Whether repeating the same request later may succeed.
    """

    retryable: bool = False

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailableError(ProviderError):
    """Transient failure: network error, timeout or 5xx response."""

    retryable = True


class RateLimitedError(ProviderError):
    """The provider throttled the request (HTTP 429 or quota message).

    Attributes:
        retry_after: Seconds the provider asked to wait, when it said so.
    """

    retryable = True

    def __init__(self, provider: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(provider, message)
        self.retry_after = retry_after


class AuthenticationError(ProviderError):
    """Missing, invalid or unauthorised API credentials."""


class SymbolNotFoundError(ProviderError):
    """The provider does not know the requested symbol or series."""


class UnsupportedRequestError(ProviderError):
    """The provider cannot serve this kind of request (frequency, history, asset class)."""


class ProviderDataError(ProviderError):
    """The provider answered with data that is malformed or fails domain validation."""
