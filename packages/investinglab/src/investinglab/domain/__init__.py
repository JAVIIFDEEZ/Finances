"""Domain model: immutable value objects and entities with no I/O.

Everything here is a ``@dataclass(frozen=True, slots=True)`` validated on construction.
The domain may use the numerical kernel (:mod:`investinglab.analytics`) but never I/O,
frameworks, plotting or configuration (enforced by import-linter).
"""

from investinglab.domain.errors import (
    DomainError,
    IncompatibleSeriesError,
    InvalidIdentifierError,
    InvalidPortfolioError,
    InvalidSeriesError,
    InvestingLabError,
    UnknownCurrencyError,
)
from investinglab.domain.instruments import (
    EXCHANGES,
    AssetClass,
    Exchange,
    Identifiers,
    Instrument,
)
from investinglab.domain.money import (
    CHF,
    EUR,
    GBP,
    JPY,
    USD,
    Currency,
    CurrencyKind,
    CurrencyPair,
    QuoteUnit,
    parse_quote_currency,
)
from investinglab.domain.series import (
    MIN_OBSERVATIONS,
    DataSource,
    PriceAdjustment,
    PriceField,
    PriceSeries,
    ReturnKind,
    SeriesStats,
)
from investinglab.domain.time import (
    CRYPTO_SCHEDULE,
    EQUITY_SCHEDULE,
    FX_SCHEDULE,
    Frequency,
    MarketSchedule,
)

__all__ = [
    "CHF",
    "CRYPTO_SCHEDULE",
    "EQUITY_SCHEDULE",
    "EUR",
    "EXCHANGES",
    "FX_SCHEDULE",
    "GBP",
    "JPY",
    "MIN_OBSERVATIONS",
    "USD",
    "AssetClass",
    "Currency",
    "CurrencyKind",
    "CurrencyPair",
    "DataSource",
    "DomainError",
    "Exchange",
    "Frequency",
    "Identifiers",
    "IncompatibleSeriesError",
    "Instrument",
    "InvalidIdentifierError",
    "InvalidPortfolioError",
    "InvalidSeriesError",
    "InvestingLabError",
    "MarketSchedule",
    "PriceAdjustment",
    "PriceField",
    "PriceSeries",
    "QuoteUnit",
    "ReturnKind",
    "SeriesStats",
    "UnknownCurrencyError",
    "parse_quote_currency",
]
