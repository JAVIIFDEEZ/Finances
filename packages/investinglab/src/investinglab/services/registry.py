"""Registry of data providers and routing preferences.

Providers are registered once (by the composition root) and the router returns, for each
request, the ordered list of providers able to serve it: an explicit preference order when
one is configured for that asset class and/or frequency, then every other capable provider
as a last-resort fallback, in registration order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from investinglab.domain.errors import DomainError
from investinglab.ports.market_data import Dataset, EconomicDataProvider, MarketDataProvider

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from investinglab.domain.instruments import AssetClass
    from investinglab.domain.time import Frequency
    from investinglab.ports.market_data import BarsRequest, EconomicRequest

__all__ = ["ProviderRegistry"]

type _RouteKey = tuple[AssetClass | None, Frequency | None]


class ProviderRegistry:
    """Registered providers plus the preference order used to route requests."""

    def __init__(self) -> None:
        self._bars: dict[str, MarketDataProvider] = {}
        self._economic: dict[str, EconomicDataProvider] = {}
        self._routes: dict[_RouteKey, tuple[str, ...]] = {}

    def register(self, provider: MarketDataProvider | EconomicDataProvider) -> None:
        """Register a provider under its name for every dataset it declares.

        Raises:
            DomainError: If a provider with the same name is already registered, or the
                provider declares a dataset it does not implement.
        """
        name = provider.name
        if name in self._bars or name in self._economic:
            raise DomainError(f"Provider {name!r} is already registered")
        datasets = provider.capabilities.datasets
        if Dataset.BARS in datasets:
            if not isinstance(provider, MarketDataProvider):
                raise DomainError(f"Provider {name!r} declares bars but has no fetch_bars()")
            self._bars[name] = provider
        if Dataset.ECONOMIC in datasets:
            if not isinstance(provider, EconomicDataProvider):
                raise DomainError(
                    f"Provider {name!r} declares economic data but has no fetch_economic_series()"
                )
            self._economic[name] = provider

    def prefer(
        self,
        providers: Sequence[str],
        *,
        asset_class: AssetClass | None = None,
        frequency: Frequency | None = None,
    ) -> None:
        """Set the preferred provider order for an asset class and/or a frequency.

        The most specific rule wins: (asset class, frequency), then asset class only, then
        frequency only, then the registration order.

        Raises:
            DomainError: If a name is not a registered bars provider.
        """
        unknown = [name for name in providers if name not in self._bars]
        if unknown:
            raise DomainError(f"Unknown bars providers {unknown}; register them first")
        self._routes[asset_class, frequency] = tuple(providers)

    @property
    def names(self) -> tuple[str, ...]:
        """Names of every registered provider, in registration order."""
        return tuple(dict.fromkeys([*self._bars, *self._economic]))

    def __contains__(self, name: object) -> bool:
        return name in self._bars or name in self._economic

    def bars_candidates(self, request: BarsRequest, today: date) -> list[MarketDataProvider]:
        """Providers able to serve ``request``, in preference order."""
        preferred = self._preferred_order(request.asset_class, request.frequency)
        ordered = [*preferred, *(name for name in self._bars if name not in preferred)]
        return [
            self._bars[name]
            for name in ordered
            if self._bars[name].capabilities.can_serve_bars(request, today)
        ]

    def economic_candidates(self, request: EconomicRequest) -> list[EconomicDataProvider]:
        """Providers of economic series, in registration order."""
        del request  # every economic provider is a candidate; ids are provider-specific
        return list(self._economic.values())

    def _preferred_order(
        self, asset_class: AssetClass | None, frequency: Frequency | None
    ) -> tuple[str, ...]:
        for key in ((asset_class, frequency), (asset_class, None), (None, frequency)):
            if key in self._routes:
                return self._routes[key]
        return ()
