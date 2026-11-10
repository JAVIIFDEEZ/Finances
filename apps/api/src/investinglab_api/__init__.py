"""InvestingLab REST API (FastAPI): the core library over HTTP for the web app (ADR-0027)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("investinglab-api")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
