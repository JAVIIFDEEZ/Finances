"""Fixtures of the API tests: the app over SYNTHETIC series, never the network.

The series come from ``support.factories`` (seeded geometric Brownian motion, provider
``synthetic``): they prove the API works, not any market result.
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from investinglab.config import Settings, get_settings
from investinglab.domain import (
    USD,
    AssetClass,
    FlowSeries,
    Frequency,
    PriceSeries,
    RateKind,
    RateSeries,
)
from investinglab.toolkit import AsyncToolkit
from investinglab_api.app import create_app
from investinglab_api.persistence import Database
from investinglab_api.persistence.ddl import APP_ROLE
from investinglab_api.persistence.migrate import upgrade
from investinglab_api.settings import ApiSettings, get_api_settings
from support.factories import (
    SYNTHETIC_SOURCE,
    business_days,
    gbm_prices,
    make_economic_series,
    make_fx_series,
    make_instrument,
    make_series,
)
from support.fakes import (
    FakeBarsProvider,
    FakeEconomicProvider,
    FakeFlowProvider,
    FakeRatesProvider,
)
from support.repositories import InMemoryPortfolioRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from pathlib import Path

DAYS = business_days(600, start="2023-01-02")

# Read at import: the tests then run without any INVESTINGLAB_* variable (see below).
TEST_DATABASE_URL = os.environ.get("INVESTINGLAB_TEST_DATABASE_URL")
"""Administrator URL of a PostgreSQL server for the tests (they create their own database)."""
EUROPEAN = ("AAA.MC", "BBB.MC", "CCC.MC")


def synthetic_bars(symbol: str, index: pd.DatetimeIndex, *, seed: int) -> PriceSeries:
    """SYNTHETIC open, high, low and close: a random walk, open and close within each range."""
    rng = np.random.default_rng(seed)
    close = gbm_prices(len(index), seed=seed)
    spread = rng.uniform(0.002, 0.02, len(index))
    high, low = close * (1 + spread), close * (1 - spread)
    frequency = Frequency.HOUR_1 if index.tz is not None else Frequency.DAY_1
    return PriceSeries(
        instrument=make_instrument(symbol),
        frequency=frequency,
        source=SYNTHETIC_SOURCE,
        data=pd.DataFrame(
            {
                "open": low + rng.uniform(0, 1, len(index)) * (high - low),
                "high": high,
                "low": low,
                "close": close,
            },
            index=index,
        ),
    )


def market_hours(days: int) -> pd.DatetimeIndex:
    """Hourly bars of the Madrid session (09:00-16:00 local) over ``days`` business days."""
    local = [
        pd.Timestamp(f"{day.date()} {hour:02d}:00", tz="Europe/Madrid")
        for day in business_days(days, start="2024-03-04")
        for hour in range(9, 17)
    ]
    return pd.DatetimeIndex(local).tz_convert("UTC")


def synthetic_series() -> list[PriceSeries]:
    """Three EUR equities, a USD equity, its USD→EUR fixings, an hourly series, and two with
    open, high and low (daily and hourly, for the price patterns)."""
    series = [
        make_series(
            gbm_prices(len(DAYS), mu=0.04 + 0.02 * i, sigma=0.15 + 0.05 * i, seed=i + 1),
            symbol=symbol,
            index=DAYS,
        )
        for i, symbol in enumerate(EUROPEAN)
    ]
    series.append(
        make_series(gbm_prices(len(DAYS), seed=11), symbol="USD.US", index=DAYS, currency=USD)
    )
    series.append(
        make_fx_series(
            gbm_prices(len(DAYS), mu=0.0, sigma=0.05, s0=0.9, seed=12), pair="USDEUR", index=DAYS
        )
    )
    hours = pd.date_range("2024-03-04 08:00", periods=40, freq="1h", tz="UTC")
    series.append(
        make_series(
            gbm_prices(len(hours), seed=13),
            symbol="HOURLY.MC",
            index=hours,
            frequency=Frequency.HOUR_1,
        )
    )
    series.append(synthetic_bars("BARS.MC", DAYS, seed=31))
    series.append(synthetic_bars("SESSION.MC", market_hours(20), seed=32))
    return series


def synthetic_flow() -> list[FlowSeries]:
    """SYNTHETIC flow: a pair with its aggressor side and a listed share with volume only."""
    rng = np.random.default_rng(21)
    days = DAYS[:60]
    volume = rng.uniform(100.0, 200.0, len(days))
    pair = make_instrument("SYN/USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)
    traded = pd.DataFrame(
        {
            "volume": volume,
            "quote_volume": volume * 50.0,
            "trades": rng.integers(10, 50, len(days)).astype(float),
            "buy_volume": volume * rng.uniform(0.3, 0.7, len(days)),
        },
        index=days,
    )
    listed = pd.DataFrame({"volume": volume * 1_000}, index=days)
    return [
        FlowSeries(pair, Frequency.DAY_1, SYNTHETIC_SOURCE, traded),
        FlowSeries(make_instrument("AAA.MC"), Frequency.DAY_1, SYNTHETIC_SOURCE, listed),
    ]


def synthetic_funding() -> RateSeries:
    """SYNTHETIC funding of a perpetual swap, settled every 8 hours."""
    instants = pd.date_range("2024-03-01", periods=30, freq="8h", tz="UTC")
    rates = np.random.default_rng(22).normal(0.0001, 0.0001, len(instants))
    swap = make_instrument(
        "SYN/USDT:USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None
    )
    return RateSeries(
        swap,
        "synthetic-venue",
        RateKind.FUNDING,
        SYNTHETIC_SOURCE,
        pd.Series(rates, index=instants),
    )


def synthetic_estr() -> object:
    """A synthetic €STR at 3 %, each month published at the start of the next."""
    months = pd.date_range("2022-12-01", "2025-06-01", freq="MS")
    rows = [
        (str(month.date()), str((month + pd.offsets.MonthBegin(1)).date()), 3.0) for month in months
    ]
    return make_economic_series("ECBESTRVOLWGTTRMDMNRT", rows=rows)


@pytest.fixture(autouse=True)
def _isolated_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Ignore the developer's environment and never reach the network."""
    for key in list(os.environ):
        if key.startswith("INVESTINGLAB_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("INVESTINGLAB_OFFLINE", "true")
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    get_settings.cache_clear()
    get_api_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_api_settings.cache_clear()


@pytest.fixture
def bars() -> FakeBarsProvider:
    """The synthetic bars provider (inspect its calls or add errors in a test)."""
    return FakeBarsProvider("synthetic", {s.symbol: s for s in synthetic_series()})


@pytest.fixture
def core_settings(tmp_path: Path) -> Settings:
    """Core settings with a private data folder."""
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def toolkit(bars: FakeBarsProvider, core_settings: Settings) -> AsyncToolkit:
    """A toolkit over the synthetic providers."""
    rates = FakeEconomicProvider("rates", {"ECBESTRVOLWGTTRMDMNRT": synthetic_estr()})  # type: ignore[dict-item]
    flow = FakeFlowProvider("synthetic-flow", {f.symbol: f for f in synthetic_flow()})
    funding = FakeRatesProvider("synthetic-venue", {"SYN/USDT:USDT": synthetic_funding()})
    return AsyncToolkit.from_settings(
        core_settings, providers=[bars, rates, flow, funding], cache=False
    )


@pytest.fixture
def saved() -> InMemoryPortfolioRepository:
    """The in-memory repository the ``client`` saves portfolios in."""
    return InMemoryPortfolioRepository()


@pytest.fixture
def client(
    toolkit: AsyncToolkit, core_settings: Settings, saved: InMemoryPortfolioRepository
) -> Iterator[TestClient]:
    """A client of the API wired to the synthetic providers and an in-memory repository."""
    app = create_app(ApiSettings(), core_settings=core_settings, toolkit=toolkit, portfolios=saved)
    with TestClient(app) as test_client:
        yield test_client


# ── PostgreSQL ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def postgres() -> Iterator[dict[str, str]]:
    """A fresh, migrated database: its administrator URL and the application's.

    The application connects with a role that only has the privileges of ``investinglab_app``
    (no superuser, no ownership), as in production: row-level security and the append-only
    triggers bind it. Skipped without ``INVESTINGLAB_TEST_DATABASE_URL``; in CI that is an
    error, never a silent skip.
    """
    if TEST_DATABASE_URL is None:
        if os.environ.get("CI"):
            pytest.fail(
                "CI must set INVESTINGLAB_TEST_DATABASE_URL: the database tests ran nowhere"
            )
        pytest.skip("needs PostgreSQL: set INVESTINGLAB_TEST_DATABASE_URL")
    server = make_url(TEST_DATABASE_URL)
    suffix = secrets.token_hex(4)
    name, role, password = (
        f"investinglab_test_{suffix}",
        f"investinglab_app_{suffix}",
        secrets.token_hex(8),
    )
    connection = server.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(connection, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    owner = server.set(database=name)
    upgrade(owner.render_as_string(hide_password=False))
    with psycopg.connect(connection, autocommit=True) as admin:
        admin.execute(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}' IN ROLE {APP_ROLE}")
    try:
        yield {
            "owner": owner.render_as_string(hide_password=False),
            "app": owner.set(username=role, password=password).render_as_string(
                hide_password=False
            ),
        }
    finally:
        with psycopg.connect(connection, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
            admin.execute(f'DROP ROLE "{role}"')


@pytest.fixture
async def database(postgres: dict[str, str]) -> AsyncIterator[Database]:
    """The database as the application sees it (restricted role)."""
    db = Database(postgres["app"])
    yield db
    await db.dispose()


type Body = dict[str, object]


@pytest.fixture
def portfolio() -> Callable[..., Body]:
    """Build the request body of a portfolio of the synthetic equities (fields overridable)."""

    def build(**changes: object) -> Body:
        body: Body = {
            "name": "Synthetic core",
            "holdings": [
                {"symbol": "AAA.MC", "weight": 0.5},
                {"symbol": "BBB.MC", "weight": 0.3},
                {"symbol": "CCC.MC", "weight": 0.2},
            ],
        }
        body.update(changes)
        return body

    return build
