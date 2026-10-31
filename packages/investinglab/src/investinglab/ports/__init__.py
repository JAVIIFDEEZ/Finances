"""Ports: the interfaces (Protocols) the core expects from the outside world.

Services depend on these abstractions; adapters implement them.
"""

from investinglab.ports.calendar import CalendarUnavailableError, TradingCalendar
from investinglab.ports.errors import (
    AuthenticationError,
    ProviderDataError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from investinglab.ports.market_data import (
    BarsRequest,
    Dataset,
    EconomicDataProvider,
    EconomicRequest,
    MarketDataProvider,
    ProviderCapabilities,
    RateLimit,
    VintageMode,
)
from investinglab.ports.storage import CachedBars, CachedEconomicSeries, SeriesStore

__all__ = [
    "AuthenticationError",
    "BarsRequest",
    "CachedBars",
    "CachedEconomicSeries",
    "CalendarUnavailableError",
    "Dataset",
    "EconomicDataProvider",
    "EconomicRequest",
    "MarketDataProvider",
    "ProviderCapabilities",
    "ProviderDataError",
    "ProviderError",
    "ProviderUnavailableError",
    "RateLimit",
    "RateLimitedError",
    "SeriesStore",
    "SymbolNotFoundError",
    "TradingCalendar",
    "UnsupportedRequestError",
    "VintageMode",
]
