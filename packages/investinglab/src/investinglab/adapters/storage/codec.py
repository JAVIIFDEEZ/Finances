"""JSON-friendly encoding of domain metadata stored alongside cached data."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from investinglab.domain.instruments import EXCHANGES, AssetClass, Exchange, Identifiers, Instrument
from investinglab.domain.money import Currency
from investinglab.domain.series import DataSource
from investinglab.domain.time import Frequency, MarketSchedule
from investinglab.ports.market_data import BarsRequest, EconomicRequest, VintageMode

__all__ = [
    "decode_bars_request",
    "decode_economic_request",
    "decode_instrument",
    "decode_source",
    "encode_bars_request",
    "encode_economic_request",
    "encode_instrument",
    "encode_source",
]

type JSONDict = dict[str, Any]


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def encode_instrument(instrument: Instrument) -> JSONDict:
    """Encode an instrument, including its full venue so unknown venues round-trip."""
    exchange = instrument.exchange
    return {
        "symbol": instrument.symbol,
        "name": instrument.name,
        "asset_class": instrument.asset_class.value,
        "currency": instrument.currency.code,
        "exchange": None
        if exchange is None
        else {
            "code": exchange.code,
            "name": exchange.name,
            "timezone": exchange.timezone,
            "sessions_per_year": exchange.schedule.sessions_per_year,
            "session_hours": exchange.schedule.session_hours,
        },
        "identifiers": asdict(instrument.identifiers),
    }


def decode_instrument(data: JSONDict) -> Instrument:
    """Inverse of :func:`encode_instrument`."""
    raw_exchange = data.get("exchange")
    exchange: Exchange | None = None
    if raw_exchange is not None:
        known = EXCHANGES.get(raw_exchange["code"])
        schedule = MarketSchedule(raw_exchange["sessions_per_year"], raw_exchange["session_hours"])
        candidate = Exchange(
            raw_exchange["code"], raw_exchange["name"], raw_exchange["timezone"], schedule
        )
        exchange = known if known == candidate else candidate
    return Instrument(
        symbol=data["symbol"],
        name=data["name"],
        asset_class=AssetClass(data["asset_class"]),
        currency=Currency(data["currency"]),
        exchange=exchange,
        identifiers=Identifiers(**data.get("identifiers", {})),
    )


def encode_source(source: DataSource) -> JSONDict:
    """Encode a data source."""
    return {
        "provider": source.provider,
        "retrieved_at": source.retrieved_at.isoformat(),
        "dataset": source.dataset,
    }


def decode_source(data: JSONDict) -> DataSource:
    """Inverse of :func:`encode_source`."""
    return DataSource(
        provider=data["provider"],
        retrieved_at=datetime.fromisoformat(data["retrieved_at"]),
        dataset=data.get("dataset"),
    )


def encode_bars_request(request: BarsRequest) -> JSONDict:
    """Encode a bars request (the coverage of a cache entry)."""
    return {
        "symbol": request.symbol,
        "frequency": request.frequency.value,
        "start": _iso(request.start),
        "end": _iso(request.end),
        "asset_class": request.asset_class.value if request.asset_class else None,
    }


def decode_bars_request(data: JSONDict) -> BarsRequest:
    """Inverse of :func:`encode_bars_request`."""
    asset_class = data.get("asset_class")
    return BarsRequest(
        symbol=data["symbol"],
        frequency=Frequency(data["frequency"]),
        start=_date(data.get("start")),
        end=_date(data.get("end")),
        asset_class=AssetClass(asset_class) if asset_class else None,
    )


def encode_economic_request(request: EconomicRequest) -> JSONDict:
    """Encode an economic request (the coverage of a cache entry)."""
    return {
        "series_id": request.series_id,
        "start": _iso(request.start),
        "end": _iso(request.end),
        "mode": request.mode.value,
    }


def decode_economic_request(data: JSONDict) -> EconomicRequest:
    """Inverse of :func:`encode_economic_request`."""
    return EconomicRequest(
        series_id=data["series_id"],
        start=_date(data.get("start")),
        end=_date(data.get("end")),
        mode=VintageMode(data["mode"]),
    )
