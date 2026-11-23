"""Registry of data providers and routing preferences.

Providers are registered once (by the composition root) and the router returns, for each
request, the ordered list of providers able to serve it: an explicit preference order when
one is configured for that asset class and/or frequency, then every other capable provider
as a last-resort fallback, in registration order. Flow follows the same preferences as the
price bars, since a venue's flow describes its own bars. Holding rates have preferences of
their own, by kind: which venue's funding to read when none is named.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from investinglab.domain.errors import DomainError
from investinglab.ports.market_data import (
    BookDepthProvider,
    Dataset,
    EconomicDataProvider,
    HoldingRatesProvider,
    MarketDataProvider,
    PositioningProvider,
    TradeFlowProvider,
)
from investinglab.ports.reference import ReferenceDataProvider

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from investinglab.domain.instruments import AssetClass
    from investinglab.domain.rate_series import RateKind
    from investinglab.domain.time import Frequency
    from investinglab.ports.market_data import (
        BarsRequest,
        BookDepthRequest,
        EconomicRequest,
        PositioningRequest,
        ProviderCapabilities,
        RatesRequest,
    )

__all__ = ["AnyProvider", "ProviderRegistry"]

type AnyProvider = (
    MarketDataProvider
    | EconomicDataProvider
    | TradeFlowProvider
    | HoldingRatesProvider
    | PositioningProvider
    | BookDepthProvider
    | ReferenceDataProvider
)
"""A provider of at least one dataset."""

type _RouteKey = tuple[AssetClass | None, Frequency | None]

_METHODS: dict[Dataset, tuple[type, str]] = {
    Dataset.BARS: (MarketDataProvider, "fetch_bars"),
    Dataset.ECONOMIC: (EconomicDataProvider, "fetch_economic_series"),
    Dataset.FLOW: (TradeFlowProvider, "fetch_flow"),
    Dataset.HOLDING_RATES: (HoldingRatesProvider, "fetch_rates"),
    Dataset.POSITIONING: (PositioningProvider, "fetch_positioning"),
    Dataset.BOOK_DEPTH: (BookDepthProvider, "fetch_book_depth"),
    Dataset.REFERENCE: (ReferenceDataProvider, "fetch_market_snapshot"),
}


class ProviderRegistry:
    """Registered providers plus the preference order used to route requests."""

    def __init__(self) -> None:
        self._providers: dict[str, AnyProvider] = {}
        self._bars: dict[str, MarketDataProvider] = {}
        self._economic: dict[str, EconomicDataProvider] = {}
        self._flow: dict[str, TradeFlowProvider] = {}
        self._rates: dict[str, HoldingRatesProvider] = {}
        self._positioning: dict[str, PositioningProvider] = {}
        self._positioning_order: tuple[str, ...] = ()
        self._book_depth: dict[str, BookDepthProvider] = {}
        self._book_depth_order: tuple[str, ...] = ()
        self._reference: dict[str, ReferenceDataProvider] = {}
        self._routes: dict[_RouteKey, tuple[str, ...]] = {}
        self._rate_routes: dict[RateKind, tuple[str, ...]] = {}

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
        if isinstance(provider, PositioningProvider) and Dataset.POSITIONING in datasets:
            self._positioning[name] = provider
        if isinstance(provider, BookDepthProvider) and Dataset.BOOK_DEPTH in datasets:
            self._book_depth[name] = provider
        if isinstance(provider, ReferenceDataProvider) and Dataset.REFERENCE in datasets:
            self._reference[name] = provider

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

    def prefer_rates(self, providers: Sequence[str], *, kind: RateKind) -> None:
        """Set the order in which providers are asked for rates of ``kind`` without a venue.

        A request that names its venue only goes to that venue's provider, whatever the order.

        Raises:
            DomainError: If a name is not a registered provider of holding rates.
        """
        unknown = [name for name in providers if name not in self._rates]
        if unknown:
            raise DomainError(f"Unknown rates providers {unknown}; register them first")
        self._rate_routes[kind] = tuple(providers)

    def prefer_positioning(self, providers: Sequence[str]) -> None:
        """Set the order in which providers are asked for positioning without a venue.

        Raises:
            DomainError: If a name is not a registered provider of positioning.
        """
        unknown = [name for name in providers if name not in self._positioning]
        if unknown:
            raise DomainError(f"Unknown positioning providers {unknown}; register them first")
        self._positioning_order = tuple(providers)

    def prefer_book_depth(self, providers: Sequence[str]) -> None:
        """Set the order in which providers are asked for book depth without a venue.

        Raises:
            DomainError: If a name is not a registered provider of book depth.
        """
        unknown = [name for name in providers if name not in self._book_depth]
        if unknown:
            raise DomainError(f"Unknown book depth providers {unknown}; register them first")
        self._book_depth_order = tuple(providers)

    @property
    def names(self) -> tuple[str, ...]:
        """Names of every registered provider, in registration order."""
        return tuple(self._providers)

    @property
    def providers(self) -> tuple[AnyProvider, ...]:
        """Every registered provider, in registration order."""
        return tuple(self._providers.values())

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
        """Providers able to serve ``request``: the preferred ones for its kind, then the rest.

        A request for a named venue only goes to the provider of that venue.
        """
        preferred = self._rate_routes.get(request.kind, ())
        ordered = [*preferred, *(name for name in self._rates if name not in preferred)]
        return [
            self._rates[name]
            for name in ordered
            if request.venue in {None, name}
            and self._rates[name].capabilities.can_serve_rates(request)
        ]

    def positioning_candidates(self, request: PositioningRequest) -> list[PositioningProvider]:
        """Providers able to serve ``request``: the preferred ones, then the rest.

        A request for a named venue only goes to the provider of that venue.
        """
        preferred = self._positioning_order
        ordered = [*preferred, *(name for name in self._positioning if name not in preferred)]
        return [
            self._positioning[name]
            for name in ordered
            if request.venue in {None, name}
            and self._positioning[name].capabilities.can_serve_positioning(request)
        ]

    def book_depth_candidates(self, request: BookDepthRequest) -> list[BookDepthProvider]:
        """Providers able to serve ``request``: the preferred ones, then the rest.

        A request for a named venue only goes to the provider of that venue.
        """
        preferred = self._book_depth_order
        ordered = [*preferred, *(name for name in self._book_depth if name not in preferred)]
        return [
            self._book_depth[name]
            for name in ordered
            if request.venue in {None, name}
            and self._book_depth[name].capabilities.can_serve_book_depth(request)
        ]

    def reference_candidates(self, asset_class: AssetClass) -> list[ReferenceDataProvider]:
        """Providers of the reference data of ``asset_class``'s market, in registration order."""
        return [
            provider
            for provider in self._reference.values()
            if provider.capabilities.can_serve_reference(asset_class)
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
