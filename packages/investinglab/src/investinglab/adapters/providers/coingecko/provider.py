"""CoinGecko: snapshots of the crypto market, its dominance and its ranking (ADR-0045).

CoinGecko publishes, without an API key, the size of the whole crypto market (``/global``) and
the largest assets by capitalisation (``/coins/markets``). Both are snapshots: CoinGecko
recomputes them every few minutes and keeps no free history of them, so the adapter returns
them dated, never as series.

* **The whole market** (:class:`~investinglab.domain.MarketSnapshot`): total capitalisation
  and 24-hour volume in the currency asked, how many assets CoinGecko tracks and the share
  of the ten largest. CoinGecko gives the 24-hour change in dollars only: in another
  currency it is left out rather than passed off as the change in that currency.
* **The ranking** (:class:`~investinglab.domain.MarketCapRanking`): up to :data:`MAX_TOP`
  assets at once, by capitalisation, each with the time CoinGecko last updated it. A
  capitalisation CoinGecko reports as 0 means it does not know it: it is ``None``.
* **Quota.** Without a key CoinGecko allows a few calls a minute; a free *demo* key
  (``INVESTINGLAB_COINGECKO_API_KEY``) raises it. The key goes in a header, never in the URL,
  so it is in neither the logs nor the recordings. Demo keys are for personal use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from investinglab.adapters.http import HttpClient
from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import AssetClass
from investinglab.domain.market_reference import (
    MarketCapRanking,
    MarketShare,
    MarketSnapshot,
    RankedAsset,
)
from investinglab.domain.money import USD
from investinglab.domain.series import DataSource
from investinglab.ports.errors import ProviderDataError, UnsupportedRequestError
from investinglab.ports.market_data import Canary, Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import httpx
    from pydantic import SecretStr

    from investinglab.adapters.http import RetryPolicy
    from investinglab.ports.errors import ProviderError
    from investinglab.ports.reference import MarketCapRequest, MarketSnapshotRequest

__all__ = ["BASE_URL", "KEY_HEADER", "MAX_TOP", "NAME", "CoinGeckoProvider", "http_client"]

NAME: Final = "coingecko"
BASE_URL: Final = "https://api.coingecko.com/api/v3"
KEY_HEADER: Final = "x-cg-demo-api-key"
"""Header of a demo key: in a header, never in the URL."""

MAX_TOP: Final = 250
"""Most assets CoinGecko ranks in one call."""

PUBLIC_LIMITS: Final = (RateLimit(5, 60.0),)
"""Without a key: CoinGecko allows 5 to 15 calls a minute depending on its load; the floor."""
DEMO_LIMITS: Final = (RateLimit(30, 60.0),)
"""With a free demo key."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def explain_error(response: httpx.Response, path: str) -> ProviderError | None:
    """CoinGecko's own reason for a refused request (``invalid vs_currency``)."""
    if response.status_code != 400:  # noqa: PLR2004 - a bad request says why
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    reason = body.get("error") if isinstance(body, dict) else None
    return UnsupportedRequestError(NAME, f"{path}: {reason}") if isinstance(reason, str) else None


def http_client(
    *,
    api_key: SecretStr | None = None,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for CoinGecko: its base URL, quota and, if given, the demo key."""
    headers = {KEY_HEADER: api_key.get_secret_value()} if api_key is not None else None
    return HttpClient(
        NAME,
        base_url=BASE_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=DEMO_LIMITS if api_key is not None else PUBLIC_LIMITS,
        headers=headers,
        transport=transport,
        explain=explain_error,
    )


class _Global(BaseModel):
    model_config = ConfigDict(frozen=True)

    active_cryptocurrencies: int | None = None
    total_market_cap: dict[str, float] = Field(default_factory=dict)
    total_volume: dict[str, float] = Field(default_factory=dict)
    market_cap_percentage: dict[str, float] = Field(default_factory=dict)
    market_cap_change_percentage_24h_usd: float | None = None
    updated_at: int


class _GlobalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: _Global


class _Coin(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    symbol: str
    name: str
    current_price: float | None = None
    market_cap: float | None = None
    total_volume: float | None = None
    circulating_supply: float | None = None
    max_supply: float | None = None
    last_updated: datetime | None = None


class CoinGeckoProvider:
    """The crypto market's size, dominance and ranking, with or without a demo key.

    Args:
        api_key: A free CoinGecko demo key, for a higher quota; none by default.
        client: HTTP client to use; :func:`http_client` by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); dates the ranking's download.
    """

    def __init__(
        self,
        *,
        api_key: SecretStr | None = None,
        client: HttpClient | None = None,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._keyed = api_key is not None
        self._client = client or http_client(api_key=api_key, timeout=timeout, retry=retry)
        self._clock = clock

    @property
    def name(self) -> str:
        """Provider slug."""
        return NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Reference data of the crypto market."""
        return ProviderCapabilities(
            canary=Canary(Dataset.REFERENCE, AssetClass.CRYPTO.value),
            datasets=frozenset({Dataset.REFERENCE}),
            asset_classes=frozenset({AssetClass.CRYPTO}),
            rate_limits=DEMO_LIMITS if self._keyed else PUBLIC_LIMITS,
        )

    def _crypto_only(self, asset_class: AssetClass) -> None:
        if asset_class is not AssetClass.CRYPTO:
            raise UnsupportedRequestError(NAME, f"CoinGecko covers crypto, not {asset_class}")

    async def fetch_market_snapshot(self, request: MarketSnapshotRequest) -> MarketSnapshot:
        """The crypto market as CoinGecko last computed it, in ``request.currency``.

        Raises:
            UnsupportedRequestError: If the market is not crypto or CoinGecko gives no total
                in that currency.
            ProviderDataError: If the payload is malformed.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        self._crypto_only(request.asset_class)
        raw = await self._client.get_json("/global")
        try:
            data = _GlobalResponse.model_validate(raw).data
        except ValidationError as error:
            raise ProviderDataError(NAME, f"malformed /global answer ({error})") from None
        code = str(request.currency).lower()
        total = data.total_market_cap.get(code)
        if total is None:
            raise UnsupportedRequestError(NAME, f"CoinGecko gives no total in {request.currency}")
        # The change is in dollars only: in another currency it would not be the same figure.
        change = data.market_cap_change_percentage_24h_usd if request.currency == USD else None
        try:
            return MarketSnapshot(
                AssetClass.CRYPTO,
                request.currency,
                datetime.fromtimestamp(data.updated_at, tz=UTC),
                DataSource(NAME, self._clock(), "global"),
                total_market_cap=total,
                total_volume_24h=data.total_volume.get(code),
                market_cap_change_24h=None if change is None else change / 100,
                assets=data.active_cryptocurrencies,
                dominance=tuple(
                    MarketShare(symbol.upper(), percent / 100)
                    for symbol, percent in data.market_cap_percentage.items()
                ),
            )
        except DomainError as error:
            raise ProviderDataError(NAME, f"/global: {error}") from error

    async def fetch_market_caps(self, request: MarketCapRequest) -> MarketCapRanking:
        """The ``request.top`` largest crypto assets by capitalisation, in ``request.currency``.

        Each asset's rank is its position in CoinGecko's ordering by capitalisation.

        Raises:
            UnsupportedRequestError: If the market is not crypto, more than :data:`MAX_TOP`
                assets are asked for, or CoinGecko does not know the currency.
            ProviderDataError: If the payload is malformed or empty.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        self._crypto_only(request.asset_class)
        if request.top > MAX_TOP:
            raise UnsupportedRequestError(
                NAME, f"CoinGecko ranks up to {MAX_TOP} assets at once, not {request.top}"
            )
        params: dict[str, str | int] = {
            "vs_currency": str(request.currency).lower(),
            "order": "market_cap_desc",
            "per_page": request.top,
            "page": 1,
            "sparkline": "false",
        }
        raw: Any = await self._client.get_json("/coins/markets", params)
        if not isinstance(raw, list):
            raise ProviderDataError(NAME, "/coins/markets: expected a list of assets")
        try:
            coins = [_Coin.model_validate(item) for item in raw]
        except ValidationError as error:
            raise ProviderDataError(NAME, f"malformed /coins/markets answer ({error})") from None
        now = self._clock()
        try:
            assets = tuple(
                RankedAsset(
                    rank=position,
                    id=coin.id,
                    symbol=coin.symbol.upper(),
                    name=coin.name,
                    price=coin.current_price,
                    # CoinGecko reports 0 when it does not know the capitalisation.
                    market_cap=coin.market_cap or None,
                    volume_24h=coin.total_volume,
                    circulating_supply=coin.circulating_supply,
                    max_supply=coin.max_supply,
                    updated=coin.last_updated,
                )
                for position, coin in enumerate(coins, start=1)
            )
            updated = [asset.updated for asset in assets if asset.updated is not None]
            return MarketCapRanking(
                AssetClass.CRYPTO,
                request.currency,
                max(updated) if updated else now,
                DataSource(NAME, now, "coins/markets"),
                assets,
            )
        except DomainError as error:
            raise ProviderDataError(NAME, f"/coins/markets: {error}") from error

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
