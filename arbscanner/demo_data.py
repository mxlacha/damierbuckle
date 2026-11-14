"""Offline fixtures (also used by the tests). Not real prices."""
from datetime import datetime, timedelta, timezone

from .kalshi import group_markets
from .oddsapi import parse_events

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
KICK = (NOW + timedelta(days=2)).replace(hour=18).isoformat().replace("+00:00", "Z")


def _k(event, ticker, name, ask_cents):
    return {"event_ticker": event, "ticker": ticker, "yes_sub_title": name,
            "title": "Buffalo at Kansas City Winner?", "status": "open",
            "yes_ask": ask_cents}


KALSHI_MARKETS = [
    # Chiefs at 44c -> big edge against a book offering Bills at +130 (2.30)
    _k("KXNFLGAME-26NOV16BUFKC", "KXNFLGAME-26NOV16BUFKC-KC", "Kansas City", 44),
    _k("KXNFLGAME-26NOV16BUFKC", "KXNFLGAME-26NOV16BUFKC-BUF", "Buffalo", 60),
    # efficient game: no arb
    _k("KXNFLGAME-26NOV16DENLV", "KXNFLGAME-26NOV16DENLV-LV", "Las Vegas", 30),
    _k("KXNFLGAME-26NOV16DENLV", "KXNFLGAME-26NOV16DENLV-DEN", "Denver", 74),
]

ODDS_PAYLOAD = [
    {"id": "g1", "sport_key": "americanfootball_nfl", "commence_time": KICK,
     "home_team": "Kansas City Chiefs", "away_team": "Buffalo Bills",
     "bookmakers": [
         {"key": "draftkings", "title": "DraftKings", "markets": [{"key": "h2h", "outcomes": [
             {"name": "Kansas City Chiefs", "price": 1.62}, {"name": "Buffalo Bills", "price": 2.30}]}]},
         {"key": "fanduel", "title": "FanDuel", "markets": [{"key": "h2h", "outcomes": [
             {"name": "Kansas City Chiefs", "price": 1.60}, {"name": "Buffalo Bills", "price": 2.25}]}]},
     ]},
    {"id": "g2", "sport_key": "americanfootball_nfl", "commence_time": KICK,
     "home_team": "Las Vegas Raiders", "away_team": "Denver Broncos",
     "bookmakers": [
         {"key": "draftkings", "title": "DraftKings", "markets": [{"key": "h2h", "outcomes": [
             {"name": "Las Vegas Raiders", "price": 3.40}, {"name": "Denver Broncos", "price": 1.33}]}]},
     ]},
]


def kalshi_events():
    return group_markets(KALSHI_MARKETS, "KXNFLGAME")


def odds_events():
    return parse_events(ODDS_PAYLOAD)
