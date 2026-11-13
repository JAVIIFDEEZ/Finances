"""Registry of data providers and routing preferences.

Providers are registered once (by the composition root) and the router returns, for each
request, the ordered list of providers able to serve it: an explicit preference order when
one is configured for that asset class and/or frequency, then every other capable provider
as a last-resort fallback, in registration order. Flow follows the same preferences as the
price bars, since a venue's flow describes its own bars.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from investinglab.domain.errors import DomainError
from investinglab.ports.market_data import (
    Dataset,
    EconomicDataProvider,
    HoldingRatesProvider,
    MarketDataProvider,
    TradeFlowProvider,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from investinglab.domain.instruments import AssetClass
    from investinglab.domain.time import Frequency
    from investinglab.ports.market_data import (
        BarsRequest,
        EconomicRequest,
        ProviderCapabilities,
        RatesRequest,
    )

__all__ = ["AnyProvider", "ProviderRegistry"]

type AnyProvider = (
    MarketDataProvider | EconomicDataProvider | TradeFlowProvider | HoldingRatesProvider
)
"""A provider of at least one dataset."""

type _RouteKey = tuple[AssetClass | None, Frequency | None]

_METHODS: dict[Dataset, tuple[type, str]] = {
    Dataset.BARS: (MarketDataProvider, "fetch_bars"),
    Dataset.ECONOMIC: (EconomicDataProvider, "fetch_economic_series"),
    Dataset.FLOW: (TradeFlowProvider, "fetch_flow"),
    Dataset.HOLDING_RATES: (HoldingRatesProvider, "fetch_rates"),
}


class ProviderRegistry:
    """Registered providers plus the preference order used to route requests."""

    def __init__(self) -> None:
        self._providers: dict[str, AnyProvider] = {}
        self._bars: dict[str, MarketDataProvider] = {}
        self._economic: dict[str, EconomicDataProvider] = {}
        self._flow: dict[str, TradeFlowProvider] = {}
        self._rates: dict[str, HoldingRatesProvider] = {}
        self._routes: dict[_RouteKey, tuple[str, ...]] = {}

    def register(self, provider: AnyProvider) -> None:
        """Register a provider under its name for every dataset it declares.

        Raises:
            DomainError: If a provider with the same name is already registered, or the
                provider declares a dataset it does not implement.
        """
        name = provider.name
        if name in self._providers:
            raise DomainError(f"Provider {name!r} is already registered")
        datasets = provider.capabilities.datasets
        for dataset in sorted(datasets):
            port, method = _METHODS[dataset]
            if not isinstance(provider, port):
                raise DomainError(
                    f"Provider {name!r} declares {dataset.value} data but has no {method}()"
                )
        self._providers[name] = provider
        if isinstance(provider, MarketDataProvider) and Dataset.BARS in datasets:
            self._bars[name] = provider
        if isinstance(provider, EconomicDataProvider) and Dataset.ECONOMIC in datasets:
            self._economic[name] = provider
        if isinstance(provider, TradeFlowProvider) and Dataset.FLOW in datasets:
            self._flow[name] = provider
        if isinstance(provider, HoldingRatesProvider) and Dataset.HOLDING_RATES in datasets:
            self._rates[name] = provider

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

        The order applies to the price bars and to their flow.

        Raises:
            DomainError: If a name is not a registered provider of bars or flow.
        """
        unknown = [name for name in providers if name not in self._bars and name not in self._flow]
        if unknown:
            raise DomainError(f"Unknown bars providers {unknown}; register them first")
        self._routes[asset_class, frequency] = tuple(providers)

    @property
    def names(self) -> tuple[str, ...]:
        """Names of every registered provider, in registration order."""
        return tuple(self._providers)

    def capabilities(self) -> dict[str, ProviderCapabilities]:
        """What each registered provider declares it can serve, in registration order."""
        return {name: provider.capabilities for name, provider in self._providers.items()}

    def __contains__(self, name: object) -> bool:
        return name in self._providers

    def bars_candidates(self, request: BarsRequest, today: date) -> list[MarketDataProvider]:
        """Providers able to serve ``request``, in preference order."""
        preferred = self._preferred_order(request.asset_class, request.frequency)
        ordered = [*preferred, *(name for name in self._bars if name not in preferred)]
        return [
            self._bars[name]
            for name in ordered
            if name in self._bars and self._bars[name].capabilities.can_serve_bars(request, today)
        ]

    def flow_candidates(self, request: BarsRequest, today: date) -> list[TradeFlowProvider]:
        """Providers able to serve the flow of ``request``'s bars, in preference order."""
        preferred = self._preferred_order(request.asset_class, request.frequency)
        ordered = [*preferred, *(name for name in self._flow if name not in preferred)]
        return [
            self._flow[name]
            for name in ordered
            if name in self._flow and self._flow[name].capabilities.can_serve_flow(request, today)
        ]

    def rates_candidates(self, request: RatesRequest) -> list[HoldingRatesProvider]:
        """Providers able to serve ``request``, in registration order.

        A request for a named venue only goes to the provider of that venue.
        """
        return [
            provider
            for name, provider in self._rates.items()
            if request.venue in {None, name} and provider.capabilities.can_serve_rates(request)
        ]

    def economic_candidates(self, request: EconomicRequest) -> list[EconomicDataProvider]:
        """Providers able to serve ``request``, in registration order."""
        return [
            provider
            for provider in self._economic.values()
            if provider.capabilities.can_serve_economic(request)
        ]

    def _preferred_order(
        self, asset_class: AssetClass | None, frequency: Frequency | None
    ) -> tuple[str, ...]:
        for key in ((asset_class, frequency), (asset_class, None), (None, frequency)):
            if key in self._routes:
                return self._routes[key]
        return ()
