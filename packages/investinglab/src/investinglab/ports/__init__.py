"""Ports: the interfaces (Protocols) the core expects from the outside world.

Services depend on these abstractions; adapters implement them.
"""

from investinglab.ports.audit_log import (
    GENESIS_HASH,
    AuditLog,
    ChainReport,
    JsonValue,
    LogEntry,
    canonical_json,
    entry_hash,
    verify_chain,
)
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
from investinglab.ports.repositories import (
    DuplicateNameError,
    Page,
    PortfolioRepository,
    PortfolioSpec,
    RecordNotFoundError,
    RepositoryError,
    RepositoryUnavailableError,
    Stored,
    VersionConflictError,
    decode_cursor,
    encode_cursor,
)
from investinglab.ports.storage import CachedBars, CachedEconomicSeries, SeriesStore

__all__ = [
    "GENESIS_HASH",
    "AuditLog",
    "AuthenticationError",
    "BarsRequest",
    "CachedBars",
    "CachedEconomicSeries",
    "CalendarUnavailableError",
    "ChainReport",
    "Dataset",
    "DuplicateNameError",
    "EconomicDataProvider",
    "EconomicRequest",
    "JsonValue",
    "LogEntry",
    "MarketDataProvider",
    "Page",
    "PortfolioRepository",
    "PortfolioSpec",
    "ProviderCapabilities",
    "ProviderDataError",
    "ProviderError",
    "ProviderUnavailableError",
    "RateLimit",
    "RateLimitedError",
    "RecordNotFoundError",
    "RepositoryError",
    "RepositoryUnavailableError",
    "SeriesStore",
    "Stored",
    "SymbolNotFoundError",
    "TradingCalendar",
    "UnsupportedRequestError",
    "VersionConflictError",
    "VintageMode",
    "canonical_json",
    "decode_cursor",
    "encode_cursor",
    "entry_hash",
    "verify_chain",
]
