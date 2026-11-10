"""Economic series the ECB adapter serves, with the day each value becomes public.

Only series whose publication rule is known are served: an economic series is used point
in time (ADR-0009), so the adapter must say when every value was first known. The ECB's
own series keys are used as identifiers (``EST.B.EU000A2X2A25.WT``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from investinglab.domain.time import Frequency

__all__ = ["CATALOGUE", "DEPOSIT_FACILITY", "ESTR", "EcbSeries", "Publication"]


class Publication(StrEnum):
    """When an observation becomes public, relative to its date."""

    SAME_DAY = "same_day"
    """Known on its own date (policy rates are announced before they take effect)."""
    NEXT_TARGET_DAY = "next_target_day"
    """Published on the next TARGET business day (€STR, at 08:00 CET)."""


@dataclass(frozen=True, slots=True)
class EcbSeries:
    """A series of the ECB Data Portal.

    Attributes:
        series_id: Full series key, dataflow first (``EST.B.EU000A2X2A25.WT``).
        title: Human-readable title.
        units: Units as published.
        frequency: Observation frequency.
        publication: When each observation becomes public.
    """

    series_id: str
    title: str
    units: str
    frequency: Frequency
    publication: Publication

    @property
    def flow(self) -> str:
        """Dataflow (``EST``, ``FM``...)."""
        return self.series_id.split(".", 1)[0]


ESTR = "EST.B.EU000A2X2A25.WT"
"""€STR: volume-weighted trimmed mean overnight rate (published since 2019-10-01)."""
DEPOSIT_FACILITY = "FM.D.U2.EUR.4F.KR.DFR.LEV"
"""Deposit facility rate in force each calendar day."""

CATALOGUE: MappingProxyType[str, EcbSeries] = MappingProxyType(
    {
        entry.series_id: entry
        for entry in (
            EcbSeries(
                ESTR,
                "Euro short-term rate (€STR), volume-weighted trimmed mean",
                "Percent per annum",
                Frequency.DAY_1,
                Publication.NEXT_TARGET_DAY,
            ),
            EcbSeries(
                DEPOSIT_FACILITY,
                "ECB deposit facility rate",
                "Percent per annum",
                Frequency.DAY_1,
                Publication.SAME_DAY,
            ),
            EcbSeries(
                "FM.D.U2.EUR.4F.KR.MRR_FR.LEV",
                "ECB main refinancing operations rate (fixed rate tenders)",
                "Percent per annum",
                Frequency.DAY_1,
                Publication.SAME_DAY,
            ),
            EcbSeries(
                "FM.D.U2.EUR.4F.KR.MLFR.LEV",
                "ECB marginal lending facility rate",
                "Percent per annum",
                Frequency.DAY_1,
                Publication.SAME_DAY,
            ),
        )
    }
)
"""Economic series served, by ECB series key."""
