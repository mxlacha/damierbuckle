"""Glue: pull Kalshi + sportsbook prices, match games, find arbitrage."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .arb import KALSHI_FEE_RATE, implied_total, kalshi_eff_odds, size_stakes
from .matching import map_names
from .models import Arb, KalshiEvent, Leg, OddsEvent

# name -> (Kalshi series ticker, Odds API sport key).
# Kalshi series tickers are best-effort; override on the CLI with --sport.
SPORTS: dict[str, tuple[str, str]] = {
    "nfl": ("KXNFLGAME", "americanfootball_nfl"),
    "ncaaf": ("KXNCAAFGAME", "americanfootball_ncaaf"),
    "nba": ("KXNBAGAME", "basketball_nba"),
    "ncaab": ("KXNCAAMBGAME", "basketball_ncaab"),
    "nhl": ("KXNHLGAME", "icehockey_nhl"),
    "mlb": ("KXMLBGAME", "baseball_mlb"),
    "epl": ("KXEPLGAME", "soccer_epl"),
    "mls": ("KXMLSGAME", "soccer_usa_mls"),
}


@dataclass
class ScanConfig:
    bankroll: float = 100.0
    min_profit_pct: float = 0.0  # may be negative to show near-misses
    fee_rate: float = KALSHI_FEE_RATE
    include_live: bool = False
    require_kalshi: bool = True  # only report arbs that use at least one Kalshi leg


def match_kalshi(odds_ev: OddsEvent, candidates: list[KalshiEvent]):
    """Find the single Kalshi event for this game, or None if none/ambiguous."""
    book_names = sorted({n for b in odds_ev.books.values() for n in b})
    day = odds_ev.commence.date()
    scored = []
    for k in candidates:
        if k.game_date and abs((k.game_date - day).days) > 1:
            continue
        names = [o.name for o in k.outcomes]
        mapping, score = map_names(names, book_names)
        if mapping is None:
            continue
        # a game needs both teams; a lone matched outcome could be anything
        team_hits = sum(1 for v in mapping.values() if v in (odds_ev.home, odds_ev.away))
        if team_hits < 2:
            continue
        exact_day = 1 if k.game_date == day else 0
        scored.append((exact_day, score, k, mapping))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    if len(scored) > 1 and scored[0][:2] == scored[1][:2]:
        return None  # e.g. doubleheader: can't tell which game is which
    return scored[0][2], scored[0][3]


def evaluate_event(odds_ev: OddsEvent, kalshi_ev: KalshiEvent, mapping: dict[str, str],
                   cfg: ScanConfig) -> Arb | None:
    shapes = Counter(frozenset(b) for b in odds_ev.books.values())
    if not shapes:
        return None
    outcome_set = shapes.most_common(1)[0][0]

    best: dict[str, Leg] = {}

    def offer(leg: Leg):
        cur = best.get(leg.outcome)
        if cur is None or leg.eff_odds > cur.eff_odds:
            best[leg.outcome] = leg

    for book, prices in odds_ev.books.items():
        if frozenset(prices) != outcome_set:
            continue  # book lists a different market shape (e.g. no draw)
        for outcome, dec in prices.items():
            offer(Leg(outcome, book, False, dec, dec, book))
    for o in kalshi_ev.outcomes:
        outcome = mapping.get(o.name)
        if outcome in outcome_set and o.yes_ask is not None:
            offer(Leg(outcome, "Kalshi", True, o.yes_ask,
                      kalshi_eff_odds(o.yes_ask, cfg.fee_rate), o.ticker))

    if set(best) != set(outcome_set):
        return None
    legs = [best[o] for o in sorted(outcome_set)]
    if cfg.require_kalshi and not any(l.is_kalshi for l in legs):
        return None
    if len({l.venue for l in legs}) < 2:
        return None
    total = implied_total(legs)
    sized, outlay, profit = size_stakes(legs, cfg.bankroll, cfg.fee_rate)
    if outlay <= 0 or any((l.is_kalshi and l.contracts == 0) or l.stake <= 0 for l in sized):
        return None  # bankroll too small to place every leg
    roi = profit / outlay
    if roi * 100 < cfg.min_profit_pct:
        return None
    return Arb(odds_ev.sport_key, f"{odds_ev.away} @ {odds_ev.home}", odds_ev.commence,
               sized, total, roi, outlay, profit, kalshi_ev.event_ticker)


def find_arbs(odds_events: list[OddsEvent], kalshi_events: list[KalshiEvent],
              cfg: ScanConfig, now: datetime | None = None) -> list[Arb]:
    now = now or datetime.now(timezone.utc)
    arbs = []
    for ev in odds_events:
        if not cfg.include_live and ev.commence <= now + timedelta(minutes=2):
            continue
        m = match_kalshi(ev, kalshi_events)
        if not m:
            continue
        arb = evaluate_event(ev, m[0], m[1], cfg)
        if arb:
            arbs.append(arb)
    return sorted(arbs, key=lambda a: a.roi, reverse=True)
