"""Point-in-time universes: who belonged to a group of instruments on each date.

Testing an idea on "the IBEX 35" or "the top 50 coins" as they are today leaves out
everything that was delisted, went bankrupt or fell out of the list, and those are exactly
the cases that made past returns worse. A :class:`Universe` records each member's dates in
and out, for any asset class, so that a study only uses what was known and tradable on
each date.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

import pandas as pd

from investinglab.domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

__all__ = ["Membership", "Survivorship", "Universe"]


@dataclass(frozen=True, slots=True, order=True)
class Membership:
    """One stay of an instrument in a universe.

    Attributes:
        symbol: Canonical symbol of the instrument.
        start: First day as a member.
        end: Last day as a member; ``None`` while it still is one.
    """

    symbol: str
    start: date
    end: date | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise DomainError("A membership needs a symbol")
        if self.end is not None and self.end < self.start:
            raise DomainError(f"{self.symbol}: leaves on {self.end}, before joining {self.start}")

    def covers(self, day: date) -> bool:
        """Whether the instrument was a member on ``day``."""
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass(frozen=True, slots=True)
class Survivorship:
    """How much of a universe was lost between two dates.

    Attributes:
        start: First date compared.
        end: Last date compared.
        initial: Members on ``start``.
        survivors: Members on ``start`` that were still members on ``end``.
        departed: Members on ``start`` that had left by ``end``.
    """

    start: date
    end: date
    initial: tuple[str, ...]
    survivors: tuple[str, ...]
    departed: tuple[str, ...]

    @property
    def attrition(self) -> float:
        """Share of the initial members that left (NaN for an empty universe)."""
        return len(self.departed) / len(self.initial) if self.initial else float("nan")


@dataclass(frozen=True, slots=True)
class Universe:
    """A named group of instruments with its history of members.

    Args:
        name: Name of the universe (``IBEX 35``, ``Top 50 crypto``…).
        memberships: Every stay of every instrument; one instrument may come and go.
        as_of: Last date the record is known to be complete for. Nothing can be asked
            about later dates.
        point_in_time: ``False`` when the list is just today's members projected back
            (see :meth:`fixed`): results on it suffer from survivorship bias, and whoever
            shows them should say so.

    Raises:
        DomainError: Overlapping stays of one instrument, or stays beyond ``as_of``.
    """

    name: str
    memberships: tuple[Membership, ...]
    as_of: date
    point_in_time: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("A universe needs a name")
        ordered = tuple(sorted(self.memberships))
        if not ordered:
            raise DomainError(f"Universe {self.name!r} has no members")
        object.__setattr__(self, "memberships", ordered)
        problems = []
        for previous, current in pairwise(ordered):
            if previous.symbol == current.symbol and (
                previous.end is None or current.start <= previous.end
            ):
                problems.append(f"{current.symbol}: overlapping stays")
        problems.extend(
            f"{stay.symbol}: {stay.start} is after as_of {self.as_of}"
            for stay in ordered
            if stay.start > self.as_of
        )
        problems.extend(
            f"{stay.symbol}: leaves on {stay.end}, after as_of {self.as_of}"
            for stay in ordered
            if stay.end is not None and stay.end > self.as_of
        )
        if problems:
            raise DomainError(f"Invalid universe {self.name!r}: " + "; ".join(problems))

    @classmethod
    def fixed(cls, name: str, symbols: Iterable[str], *, since: date, as_of: date) -> Universe:
        """Today's list of members, assumed constant since ``since``.

        It is **not** point-in-time: whatever left the group before today is missing.
        """
        stays = tuple(Membership(symbol, since) for symbol in dict.fromkeys(symbols))
        return cls(name, stays, as_of, point_in_time=False)

    @property
    def symbols(self) -> tuple[str, ...]:
        """Every instrument that was ever a member, in alphabetical order."""
        return tuple(sorted({stay.symbol for stay in self.memberships}))

    def _known(self, day: date) -> None:
        if day > self.as_of:
            raise DomainError(
                f"Universe {self.name!r} is known up to {self.as_of}: {day} is in its future"
            )

    def members(self, on: date) -> tuple[str, ...]:
        """The members on a date, in alphabetical order.

        Raises:
            DomainError: The date is after ``as_of``.
        """
        self._known(on)
        return tuple(sorted({stay.symbol for stay in self.memberships if stay.covers(on)}))

    def contains(self, symbol: str, on: date) -> bool:
        """Whether ``symbol`` was a member on a date."""
        self._known(on)
        return any(stay.symbol == symbol and stay.covers(on) for stay in self.memberships)

    def mask(self, days: pd.DatetimeIndex) -> pd.DataFrame:
        """Membership as a table: one row per date, one column per instrument ever a member.

        Multiply returns or signals by it to keep only what belonged to the universe on
        each date.

        Raises:
            DomainError: Some date is after ``as_of``.
        """
        if len(days) and days.max().date() > self.as_of:
            self._known(days.max().date())
        dates = days.tz_localize(None).normalize() if days.tz is not None else days.normalize()
        table = pd.DataFrame(data=False, index=days, columns=list(self.symbols))
        for stay in self.memberships:
            inside = dates >= pd.Timestamp(stay.start)
            if stay.end is not None:
                inside &= dates <= pd.Timestamp(stay.end)
            table[stay.symbol] |= inside
        return table

    def survivorship(self, start: date, end: date | None = None) -> Survivorship:
        """Which members on ``start`` were still members on ``end`` (``as_of`` by default)."""
        last = self.as_of if end is None else end
        if last < start:
            raise DomainError(f"end {last} is before start {start}")
        initial = self.members(start)
        final = set(self.members(last))
        return Survivorship(
            start=start,
            end=last,
            initial=initial,
            survivors=tuple(s for s in initial if s in final),
            departed=tuple(s for s in initial if s not in final),
        )
