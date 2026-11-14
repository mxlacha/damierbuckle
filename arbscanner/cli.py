from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

from . import demo_data
from .arb import KALSHI_FEE_RATE
from .kalshi import KalshiClient
from .oddsapi import OddsApiClient, OddsApiError
from .report import format_arb, to_json
from .scanner import SPORTS, ScanConfig, find_arbs


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="arbscanner",
                                description="Find Kalshi <-> sportsbook arbitrage.")
    p.add_argument("--sport", action="append", metavar="NAME[:KALSHI_SERIES:ODDS_KEY]",
                   help=f"sport to scan (repeatable). Built-in: {', '.join(SPORTS)}. "
                        "Custom: nba:KXNBAGAME:basketball_nba. Default: nfl,nba,nhl,mlb")
    p.add_argument("--bankroll", type=float, default=100.0, help="total $ to size each arb with")
    p.add_argument("--min-profit", type=float, default=0.0, metavar="PCT",
                   help="minimum guaranteed ROI %% (negative shows near-misses)")
    p.add_argument("--regions", default="us", help="Odds API regions, e.g. us,us2")
    p.add_argument("--books", help="comma list of Odds API bookmaker keys you can actually use "
                                   "(e.g. draftkings,fanduel,betmgm); overrides --regions")
    p.add_argument("--fee-rate", type=float, default=KALSHI_FEE_RATE, help="Kalshi taker fee rate")
    p.add_argument("--include-live", action="store_true", help="also scan games already started")
    p.add_argument("--allow-book-vs-book", action="store_true",
                   help="also report arbs between sportsbooks with no Kalshi leg")
    p.add_argument("--watch", type=int, metavar="SECONDS", help="repeat every N seconds")
    p.add_argument("--json", action="store_true", help="emit one JSON object per arb")
    p.add_argument("--log", metavar="FILE", help="append every arb found as JSON lines")
    p.add_argument("--demo", action="store_true", help="run on built-in offline fixtures")
    return p.parse_args(argv)


def resolve_sports(specs):
    if not specs:
        specs = ["nfl", "nba", "nhl", "mlb"]
    out = []
    for s in specs:
        parts = s.split(":")
        if len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
        elif parts[0] in SPORTS:
            out.append((parts[0], *SPORTS[parts[0]]))
        else:
            raise SystemExit(f"unknown sport {s!r}; built-ins: {', '.join(SPORTS)}")
    return out


def run_once(args, cfg, kalshi, odds, seen: set, now=None) -> int:
    found = 0
    for name, series, odds_key in resolve_sports(args.sport):
        try:
            if args.demo:
                k_events, o_events = demo_data.kalshi_events(), demo_data.odds_events()
            else:
                k_events = kalshi.events(series)
                o_events = odds.odds(odds_key, args.regions, args.books)
        except OddsApiError as e:
            raise SystemExit(str(e))
        except Exception as e:  # network blip on one sport shouldn't kill a watch loop
            print(f"[{name}] fetch failed: {e}", file=sys.stderr)
            continue
        arbs = find_arbs(o_events, k_events, cfg, now=now)
        print(f"[{name}] {len(k_events)} Kalshi games, {len(o_events)} book games, "
              f"{len(arbs)} arbs", file=sys.stderr)
        for a in arbs:
            found += 1
            sig = (a.key, round(a.roi, 3))
            if sig in seen:
                continue
            seen.add(sig)
            print(to_json(a) if args.json else format_arb(a) + "\n")
            if args.log:
                with open(args.log, "a") as f:
                    f.write(to_json(a) + "\n")
        if args.demo:
            break  # fixtures are sport-agnostic; one pass is enough
    if not args.demo and odds and odds.remaining is not None:
        print(f"(Odds API requests remaining: {odds.remaining})", file=sys.stderr)
    return found


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = ScanConfig(args.bankroll, args.min_profit, args.fee_rate, args.include_live,
                     not args.allow_book_vs_book)
    kalshi = odds = None
    now = None
    if args.demo:
        now = demo_data.NOW
    else:
        kalshi = KalshiClient()
        try:
            odds = OddsApiClient(os.environ.get("ODDS_API_KEY", ""))
        except OddsApiError as e:
            raise SystemExit(str(e))
    seen: set = set()
    while True:
        print(f"--- scan {datetime.now(timezone.utc):%H:%M:%S} UTC ---", file=sys.stderr)
        run_once(args, cfg, kalshi, odds, seen, now)
        if not args.watch:
            return 0
        time.sleep(args.watch)
