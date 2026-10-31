"""InvestingLab core library.

A framework-agnostic toolkit to ingest market data from multiple sources, model it as
immutable domain objects, analyse portfolios, run Monte Carlo simulations and produce
reports. It is usable from a notebook without the API or the database.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("investinglab")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
