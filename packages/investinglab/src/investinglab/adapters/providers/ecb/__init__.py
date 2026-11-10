"""European Central Bank provider: euro reference rates and money-market rates, no key."""

from investinglab.adapters.providers.ecb.catalogue import (
    CATALOGUE,
    DEPOSIT_FACILITY,
    ESTR,
    EcbSeries,
    Publication,
)
from investinglab.adapters.providers.ecb.provider import (
    BASE_URL,
    NAME,
    REFERENCE_CURRENCIES,
    EcbProvider,
)

__all__ = [
    "BASE_URL",
    "CATALOGUE",
    "DEPOSIT_FACILITY",
    "ESTR",
    "NAME",
    "REFERENCE_CURRENCIES",
    "EcbProvider",
    "EcbSeries",
    "Publication",
]
