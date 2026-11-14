from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class KalshiOutcome:
    ticker: str
    name: str  # team / "Draw" as Kalshi labels the YES side
    yes_ask: float | None  # dollars per $1 contract, None if nothing to buy


@dataclass(frozen=True)
class KalshiEvent:
    event_ticker: str
    series_ticker: str
    title: str
    game_date: date | None
    outcomes: tuple[KalshiOutcome, ...]


@dataclass(frozen=True)
class OddsEvent:
    event_id: str
    sport_key: str
    commence: datetime  # timezone-aware UTC
    home: str
    away: str
    # book title -> {outcome name -> decimal odds}
    books: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Leg:
    outcome: str
    venue: str  # "Kalshi" or the sportsbook title
    is_kalshi: bool
    quoted: float  # Kalshi: YES ask in dollars. Book: decimal odds.
    eff_odds: float  # decimal odds after Kalshi fees (== quoted for books)
    ref: str  # Kalshi ticker or book name
    stake: float = 0.0  # dollars to wager / spend
    contracts: int = 0  # Kalshi only


@dataclass(frozen=True)
class Arb:
    sport: str
    event: str  # "Away @ Home"
    commence: datetime
    legs: tuple[Leg, ...]
    implied_total: float  # sum(1/odds); < 1 means arbitrage
    roi: float  # guaranteed profit / outlay, after rounding to real contracts
    outlay: float
    profit: float  # guaranteed (worst case) profit, dollars
    kalshi_event: str

    @property
    def key(self) -> str:
        return f"{self.kalshi_event}|" + "|".join(f"{l.outcome}:{l.venue}" for l in self.legs)
